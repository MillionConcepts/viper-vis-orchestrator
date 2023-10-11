"""
simple integration test for raw product creation based on parameters
published by a mock yamcs server.
"""
import re
import shutil
import time

from hostess.utilities import timeout_factory
from sqlalchemy import select

import viper_orchestrator.station.definition as vsd
from viper_orchestrator.config import (
    TEST_DB_PATH, MEDIA_ROOT, ROOTS, PARAMETERS
)
from viper_orchestrator.db import OSession
from viper_orchestrator.tests.utilities import make_mock_server
from viper_orchestrator.yamcsutils.mock import MockContext, MockServer
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.light_records import LightRecord


def serve_images(max_products: int, server: MockServer):
    total_products = 0
    for i in range(max_products):
        try:
            server.serve_to_ctx(
                eng_value_imageHeader_processingInfo=8,
                eng_value_imageHeader_outputImageMask=8,  # lossy
                onboard_compression_ratio=16,
            )
            total_products += 1
            time.sleep(0.1)
        except IndexError:
            break
    return total_products


def serve_light_states(server: MockServer):
    measured_state_cols = server._pickable[
        [c for c in server._pickable.columns if re.match("eng.*measured", c)]
    ]
    off_df = (measured_state_cols == 'OFF').astype(int)
    n_light_recs = 0
    for light in off_df.columns:
        n_light_recs += (off_df[light].diff() > 0).sum()
    while True:
        try:
            server.serve_to_ctx()
        except IndexError:
            break
    return len(server._pickable), n_light_recs


# clean up, start fresh
shutil.rmtree(TEST_DB_PATH, ignore_errors=True)
shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
for folder in ROOTS:
    folder.mkdir(parents=True, exist_ok=True)
station = vsd.create_station()
station.save_port_to_shared_memory()
station.start()
vsd.launch_delegates(station)
# give delegate configuration a moment to propagate
time.sleep(0.6)
# make a shared mock context (fake websocket) for the mock yamcs server,
# image watcher, and light watcher
ctx = MockContext()
# create a mock YAMCS server attached to that shared context
print("initializing mock YAMCS server")
SERVER = make_mock_server(ctx)

try:
    # attach context to delegates
    image_watcher = station.get_delegate("image_watcher")['obj']
    light_watcher = station.get_delegate("light_watcher")['obj']
    image_watcher.sensors['image_watch'].mock_context = ctx
    light_watcher.sensors['light_watch'].mock_context = ctx
    # send some mock image publications
    MAX_PRODUCTS = 40
    SERVER.parameters = [p for p in PARAMETERS if "Images" in p]
    print("spooling mock image publications...", end="\n")
    n_products = serve_images(MAX_PRODUCTS, SERVER)
    print(f"spooled {n_products} image publications")
    waiting, unwait = timeout_factory(timeout=100)
    n_completed = len(station.inbox.completed)
    n_recs_made = 0
    # send some mock light states
    print("spooling mock light state publications...", end="\n")
    SERVER.parameters = [p for p in PARAMETERS if "Light" in p]
    n_states, n_recs = serve_light_states(SERVER)
    print(
        f"spooled {n_states} light states (representing {n_recs} LightRecords)"
    )

    def n_incomplete():
        return len(
            [n for n in station.tasks.values() if n["status"] != "success"]
        )

    while (
            (n_completed < n_products * 2)
            or (n_incomplete() > 0)
            or (n_recs_made < n_recs)
    ):
        duration = waiting()
        if station.state == "crashed":
            raise SystemError("station crashed")
        n_completed = len(station.inbox.completed)
        with OSession() as session:
            n_recs_made = session.query(LightRecord).count()
        print(
            f"{n_completed} image tasks complete; {n_incomplete()} image "
            f"tasks queued; {n_recs_made} light records created"
        )
        time.sleep(1)
    print("done", n_completed, n_completed)
    time.sleep(0.25)  # make sure last db insert had time to complete
    with OSession() as session:
        image_records = session.scalars(select(ImageRecord)).all()
        light_records = session.scalars(select(LightRecord)).all()
    assert len(image_records) == n_products
    print(image_records[0].asdict())
    print("images processed successfully")
    assert len(light_records) == n_recs
    print("light records created successfully")
finally:
    station.shutdown()
    print("application shut down successfully")
    SERVER.ctx.kill()
