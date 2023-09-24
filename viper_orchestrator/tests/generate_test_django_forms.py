import os
import random
import time

import django
from sqlalchemy import select

from viper_orchestrator.db import OSession
from viper_orchestrator.db.runtime import ENGINE
from viper_orchestrator.station import definition as vsd
from viper_orchestrator.tests.utilities import (
    sample,
    FakeWSGIRequest,
    randomize_form,
    image_records_by_compression,
    make_mock_server, make_random_pl_submission,
)
from vipersci.vis.db.image_records import ImageRecord

# note that django setup _must_ occur before importing any django application
# modules
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "viper_orchestrator.visintent.visintent.settings"
)
django.setup()
from viper_orchestrator.visintent.tracking.forms import (
    RequestForm,
    PLSubmission,
    AlreadyLosslessError,
)
from viper_orchestrator.visintent.tracking.tables import (
    ImageRequest,
    ProtectedListEntry,
)
from viper_orchestrator.visintent.tracking.views import (
    assigncaptures, intsplit,
)
from visintent.tracking.db_utils import _create_or_update_entry

# clean up
with OSession() as session:
    ImageRequest.__table__.drop(ENGINE)
    ImageRequest.metadata.create_all(ENGINE)
    ProtectedListEntry.__table__.drop(ENGINE)
    ProtectedListEntry.metadata.create_all(ENGINE)
    products = session.scalars(select(ImageRecord)).all()

# make some random RequestForms and use them to create ImageRequests in the db
for _ in range(len(products)):
    requestform = RequestForm()
    randomize_form(requestform)
    with OSession() as session:
        _create_or_update_entry(requestform, session, "capture_id")
        session.commit()

with OSession() as session:
    requests = session.scalars(select(ImageRequest)).all()
    # make sure our db inserts worked
    assert len(requests) == len(products)

# currently-correct kwargs for making create_image.create think a product
# is lossless
LOSSLESS_KWARGS = {
    'onboard_compression_ratio': 1,
    'output_image_mask': 1,
    'output_image_type': "LOSSLESS_ICER_IMAGE",
    'eng_value_imageHeader_processingInfo': 8
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
            "request-id": str(request.request_id),
        }
    )
    # assign the cluster's capture id(s) to the requests
    response = assigncaptures.__wrapped__(fakewsgi)
    # make sure that the attempt failed if the capture id was already described
    if response.content.decode("utf-8").startswith("Capture ID(s)"):
        assert len(
            set(p.capture_id for p in cluster).intersection(used_captures)
        ) != 0
        continue
    # otherwise make sure the assignment succeeded
    with OSession() as session:
        selector = select(ImageRequest).where(
            ImageRequest.request_id == fakewsgi.GET["request-id"]
        )
        request = session.scalars(selector).one()
        total_requests += 1
        assert (
            intsplit(request.capture_id)
            == intsplit(fakewsgi.GET["capture-id"])
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
lossies = random.choices(products_by_compression['lossy'], k=6)

# make sure we can put a lossy product on the protected list
lossy0 = lossies[0]
make_random_pl_submission(lossy0.product_id)
print(f"made protected list entry for {lossy0.product_id}")

# make a couple more for good measure
make_random_pl_submission(lossies[1].product_id)
make_random_pl_submission(lossies[2].product_id)

# start the Station up and create a lossless version of that product
station = vsd.create_station()
try:
    vsd.launch_delegates(station)
    station.start()
    time.sleep(0.5)  # let config propagate
    server = make_mock_server(station.get_delegate("watcher")["obj"])
    ix = server.source.loc[
        server.source["eng_value_imageHeader_lobt"] == lossy0.lobt
    ].index[0]
    server.serve_to_ctx(ix, **LOSSLESS_KWARGS)
    time.sleep(2)  # wait a healthy beat for product creation
    assert ProtectedListEntry.from_pid(lossy0.product_id).has_lossless is True
    print(
        f"checked PL response to simulated lossless downlink of "
        f"{lossy0.product_id}"
    )
    # make a different lossless product
    lossy3 = lossies[3]
    ix = server.source.loc[
        server.source["eng_value_imageHeader_lobt"] == lossy3.lobt
    ].index[0]
    server.serve_to_ctx(ix, **LOSSLESS_KWARGS)
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
    server.serve_to_ctx(
        ix,
        **LOSSLESS_KWARGS,
        instrument_name=lossy4.instrument_name,
        image_id=lossy4.image_id,
        lobt=lossy4.start_time.timestamp() + 3600
    )
    time.sleep(2)  # wait a beat
    assert ProtectedListEntry.from_pid(lossy4.product_id).superseded is True
    print("checked PL recognition of superseded entry")

finally:
    station.shutdown()
    server.ctx.kill()
    print('shut down station and mock YAMCS server')
