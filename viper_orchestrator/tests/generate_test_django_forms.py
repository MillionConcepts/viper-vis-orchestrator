import os
import random
import time

import django
from sqlalchemy import select

from viper_orchestrator.db import OSession
from viper_orchestrator.station import definition as vsd
from viper_orchestrator.tests.utilities import (
    sample,
    FakeWSGIRequest,
    randomize_form,
    image_records_by_compression,
    make_mock_server,
    make_random_pl_submission,
)
from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest

# note that django setup _must_ occur before importing any modules that
# rely on the django API
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "viper_orchestrator.visintent.visintent.settings"
)
django.setup()
from viper_orchestrator.visintent.tracking.forms import (
    RequestForm,
    PLSubmission,
)
from viper_orchestrator.exceptions import AlreadyLosslessError
from viper_orchestrator.visintent.tracking.views import (
    assign_records_from_capture_ids,
)
from viper_orchestrator.db.table_utils import intsplit
from viper_orchestrator.visintent.tracking.db_utils import (
    _create_or_update_entry,
)

# clean up
with OSession() as session:
    # cannot just drop tables because of FOREIGN KEY relationships to
    # ImageRecord
    for table in ImageRequest, ProtectedListEntry:
        rows = session.scalars(select(table)).all()
        for row in rows:
            session.delete(row)
    session.commit()
    products = session.scalars(select(ImageRecord)).all()


# make some random RequestForms and use them to create ImageRequests in the db
for _ in range(len(products)):
    requestform = RequestForm()
    randomize_form(requestform)
    requestform._reformat_camera_request()
    del requestform.cleaned_data['camera_request']
    with OSession() as session:
        _create_or_update_entry(
            requestform,
            session,
            "capture_id",
            extra_attrs=(
                "imaging_mode", "camera_type", "hazcams", "generalities"
            )
        )
        session.commit()

with OSession() as session:
    requests = session.scalars(select(ImageRequest)).all()
    # make sure our db inserts worked
    assert len(requests) == len(products)

# currently-correct kwargs for making create_image.create think a product
# is lossless
LOSSLESS_KWARGS = {
    "onboard_compression_ratio": 1,
    "output_image_mask": 1,
    "output_image_type": "LOSSLESS_ICER_IMAGE",
    "eng_value_imageHeader_processingInfo": 8,
}

# randomly cluster 9 or 10 capture ids to assign to requests, simulating
# manual assignment by VIS role; use only capture ids that actually exist
used_captures, total_requests, total_capture_ids = set(), 0, 0
psample, clusters = sample(k=10)(products), []
piter = iter(psample)
while sum(map(len, clusters)) < len(psample):
    try:
        clusters.append(
            [next(piter) for n in range(1 if random.random() > 0.25 else 2)]
        )
    except StopIteration:
        break

# mock frontend assignment of these captures
for cluster, request in zip(clusters, requests):
    fakewsgi = FakeWSGIRequest(
        {
            "capture-id": ",".join(str(p.capture_id) for p in cluster),
            "id": str(request.id),
        }
    )
    # use the cluster's capture id(s) to assign all associated ImageRecords
    # to the request
    response = assign_records_from_capture_ids.__wrapped__(fakewsgi)
    # make sure that the attempt failed if the capture id was already described
    if response.content.decode("utf-8").startswith("Capture ID(s)"):
        assert (
            len(set(p.capture_id for p in cluster).intersection(used_captures))
            != 0
        )
        continue
    # otherwise make sure the assignment succeeded
    with OSession() as session:
        selector = select(ImageRequest).where(
            ImageRequest.id == fakewsgi.GET["id"]
        )
        request = session.scalars(selector).one()
        total_requests += 1
        assert request.image_records[0].capture_id in intsplit(
            fakewsgi.GET["capture-id"]
        )
    used_captures |= set(p.capture_id for p in cluster)
    total_capture_ids += len(cluster)
print(f"assigned {total_capture_ids} capture ids to {total_requests} requests")

products_by_compression = image_records_by_compression()
# dump all lossless products
with OSession() as session:
    for product in products_by_compression["lossless"]:
        session.delete(product)
    session.commit()
products_by_compression["lossless"] = []

# pick some random products for protected list testing
lossies = random.choices(products_by_compression["lossy"], k=6)

# make sure we can put a lossy product on the protected list
lossy0 = lossies[0]
make_random_pl_submission(lossy0.product_id)
print(f"made protected list entry for {lossy0.product_id}")

# make a couple more for good measure
make_random_pl_submission(lossies[1].product_id)
make_random_pl_submission(lossies[2].product_id)

# start the Station up and create a lossless version of that product
station = vsd.create_station()
station.start()
try:
    vsd.launch_delegates(station, mock=True, update_interval=0.1)
    time.sleep(0.5)  # let config propagate
    SERVER = make_mock_server(
        station.get_delegate(
            "image_watcher"
        )["obj"].sensors['image_watch']._ctx
    )
    ix = SERVER.source.loc[
        SERVER.source["eng_value_imageHeader_lobt"] == lossy0.lobt
    ].index[0]
    # TODO: place get-one-event function on Sensor in mock mode in order to be
    #  able to replicate this in mock archive mode
    SERVER.serve_to_ctx(ix, **LOSSLESS_KWARGS)
    time.sleep(2)  # wait a healthy beat for product creation
    assert ProtectedListEntry.from_pid(lossy0.product_id).has_lossless is True
    print(
        f"checked PL response to simulated lossless downlink of "
        f"{lossy0.product_id}"
    )
    # make a different lossless product
    lossy3 = lossies[3]
    ix = SERVER.source.loc[
        SERVER.source["eng_value_imageHeader_lobt"] == lossy3.lobt
    ].index[0]
    SERVER.serve_to_ctx(ix, **LOSSLESS_KWARGS)
    time.sleep(2)  # wait a healthy beat for product creation
    # ensure user-facing functionality will refuse to create a new
    # protected list request for this already-existing lossless product
    try:
        ple = PLSubmission(product_id=lossy3.product_id)
    except Exception as ex:
        assert isinstance(ex, AlreadyLosslessError)
    print("checked PL rejection of already-lossless product")
    # make another protected list entry
    lossy4 = lossies[4]
    make_random_pl_submission(lossy4.product_id)
    # serve an image that would have "superseded" it (i.e., overwrote in CCU)
    # NOTE: will usually throw a harmless warning due to mismatched camera id
    SERVER.serve_to_ctx(
        ix,
        **LOSSLESS_KWARGS,
        instrument_name=lossy4.instrument_name,
        image_id=lossy4.image_id,
        lobt=lossy4.start_time.timestamp() + 3600,
    )
    time.sleep(2)  # wait a beat
    assert ProtectedListEntry.from_pid(lossy4.product_id).superseded is True
    print("checked PL recognition of superseded entry")

finally:
    station.shutdown()
    try:
        SERVER.ctx.kill()
    except NameError:
        pass
    print("shut down station and mock YAMCS server")
