import datetime as dt
import os
import random

import django
from sqlalchemy import select

from viper_orchestrator.db import OSession
from viper_orchestrator.db.runtime import SHUTDOWN
from viper_orchestrator.db.session import autosession
from viper_orchestrator.tests.utilities import (
    FakeWSGIRequest,
    randomize_form,
    image_records_by_compression,
    make_random_pl_submission,
    copy_imagerecord,
)
from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from viper_orchestrator.visintent.tracking.views import assign_record
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.image_tags import ImageTag

# note that django setup _must_ occur before importing any modules that
# rely on the django API
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "viper_orchestrator.visintent.visintent.settings"
)
django.setup()
from viper_orchestrator.visintent.tracking.forms import (
    RequestForm,
    PLSubmission,
    EvaluationForm,
)
from viper_orchestrator.exceptions import (
    AlreadyLosslessError,
    AlreadyDeletedError,
)
from viper_orchestrator.db.table_utils import delete_cascade, get_one


# clean up
@autosession
def dump_objects(session=None):
    # cannot just drop tables because of relationships to
    # ImageRecord, LDST, etc.
    print("dumping ImageRequests")
    image_requests = session.scalars(select(ImageRequest)).all()
    for request in image_requests:
        delete_cascade(request, ["ldst_associations"], session=session)
    print("dumping ProtectedListEntries")
    entries = session.scalars(select(ProtectedListEntry)).all()
    for entry in entries:
        delete_cascade(entry, session=session, commit=False)
    # make a bunch of additional random ImageRecords if we haven't
    images = image_records_by_compression(session=session)
    if len(images['lossy']) < 530:
        print("making 500 extra ImageRecords")
        for _ in range(530 - len(images['lossy'])):
            offset_record = copy_imagerecord(
                random.choice(images['lossy']), copy_files=True
            )
            session.add(offset_record)
    print("dumping any lossless products")
    for product in images['lossless']:
        session.delete(product)
    print("stripping VIS verification")
    for rec in images['lossy']:
        rec.verified, rec.image_tags = None, []
    session.commit()


try:
    # dump all the form-related objects and make a bunch of random ImageRecords
    dump_objects()
    # make 70 random RequestForms and use them to create ImageRequests
    for _ in range(70):
        requestform = RequestForm()
        randomize_form(requestform)
        requestform.commit()

    with OSession() as session:
        requests = session.scalars(select(ImageRequest)).all()
        # make sure our db inserts worked
        assert len(requests) == 70

    print("made 70 ImageRequests")

    # currently-correct kwargs for making create_image.create think a product
    # is lossless
    LOSSLESS_KWARGS = {
        "onboard_compression_ratio": 1,
        "output_image_mask": 1,
        "output_image_type": "LOSSLESS_ICER_IMAGE",
        "eng_value_imageHeader_processingInfo": 8,
    }

    # randomly select 1-3 ImageRecords to assign to half of these
    # ImageRequests. VIS-verify records for the first 20 requests, and no
    # others.
    with OSession() as session:
        our_records = []
        all_records = session.scalars(select(ImageRecord)).all()
        for req_ix in range(len(requests) // 2):
            records, n_records = [], random.randint(1, 2)
            while len(records) < n_records:
                rrec = random.choice(all_records)

                if rrec.id in [r.id for r in our_records]:
                    continue
                records.append(rrec)
            our_records += records
            # mock frontend assignment of these ImageRecords by VIS role
            for rec in records:
                rec: ImageRecord
                fakewsgi = FakeWSGIRequest(
                    post_values={
                        "req_id": requests[req_ix].id,
                        "rec_id": rec.id,
                        "pid": rec._pid,
                    }
                )
                # verify if in the first 20 requests
                if req_ix <= 20:
                    rec.verified = random.choice([True, False])
                    session.add(rec)
                    session.commit()
                response = assign_record(fakewsgi, session=session)
                # verify correct-ish response
                assert f"title>{rec._pid}</title" in str(response.content)
            # verify association by grabbing 'fresh' copy of ImageRequest
            req = get_one(ImageRequest, requests[req_ix].id, session=session)
            assert {r.id for r in req.image_records} == {r.id for r in records}
            # now evaluate the request if it is in the first 10 requests.
            if req_ix > 10:
                continue
            req_form = RequestForm(image_request=req)
            assert req_form.evaluation_possible is True
            if len(req_form.critical_hypotheses) == 0:
                continue
            eval_form = EvaluationForm(
                hyp=random.choice(req_form.critical_hypotheses), req_id=req.id
            )
            good = random.choice((True, False))
            eval_form.data["good"], eval_form.data["bad"] = (good, not good)
            eval_form.data["evaluator"] = "TEST_USER"
            eval_form.is_bound = True
            assert eval_form.is_valid()
            eval_form.commit()

    print(
        f"assigned {len(our_records)} records to {len(requests) // 2} requests"
    )

    # also randomly vis-verify 80 records
    images = random.sample(session.scalars(select(ImageRecord)).all(), k=80)
    for i in images:
        i.verified = random.choice((True, False))
        session.add(i)
    session.commit()
    print('randomly verified 80 records')
    products_by_compression = image_records_by_compression()

    # make sure we can put a lossy product on the protected list
    all_lossies = products_by_compression["lossy"]
    lossies = []
    # we've made a bunch of random ImageRecords, so this might fail; lazily
    # keep trying until we get some undeleted ones
    while len(lossies) < 8:
        pick = random.choice(all_lossies)
        try:
            if pick in lossies:
                continue
            # don't commit the last one, just check it can be made -- this
            # is to test functionality a little further down
            make_random_pl_submission(pick._pid, commit=len(lossies) != 4)
            lossies.append(pick)
        except AlreadyDeletedError:
            continue
    del pick
    print(
        f"made protected list entries for "
        f"{', '.join(l._pid for l in lossies)}"
    )

    with OSession() as session:
        lossless_0 = copy_imagerecord(lossies[0], offset=0, **LOSSLESS_KWARGS)
        session.add(lossless_0)
        session.commit()
        assert (
            ProtectedListEntry.from_pid(lossies[0].product_id).has_lossless
            is True
        )
        print(f"checked PL response to lossless downlink of {lossies[0]._pid}")
        # make a different lossless product, from the selected lossy product
        # we did _not_ make a PL request for
        lossless_4 = copy_imagerecord(lossies[4], offset=0, **LOSSLESS_KWARGS)
        session.add(lossless_4)
        session.commit()
        # ensure user-facing functionality will refuse to create a new
        # protected list request for this already-existing lossless product
        try:
            ple = PLSubmission(pid=lossies[4]._pid)
            raise ValueError("didn't reject submission")
        except AlreadyLosslessError:
            pass
        print("checked PL rejection of already-lossless product")
        # make another protected list entry
        make_random_pl_submission(lossies[3]._pid)
        # serve an image that would "supersede" it  (i.e., overwrite it in CCU)
        lossless_3 = copy_imagerecord(
            lossies[3],
            offset=dt.timedelta(seconds=3600),
            instrument_name=lossies[3].instrument_name,
            image_id=lossies[3].image_id,
            **LOSSLESS_KWARGS,
        )
        session.add(lossless_3)
        session.commit()
        assert ProtectedListEntry.from_pid(lossies[3]._pid).superseded is True
        print("checked PL recognition of superseded entry")
finally:
    SHUTDOWN.maybe_shut_down_postgres()
