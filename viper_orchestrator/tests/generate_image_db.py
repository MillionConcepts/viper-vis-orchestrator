"""
simple integration test for raw product creation based on parameters
published by a mock yamcs server.
"""
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
    total_light_states = 0
    while True:
        try:
            server.serve_to_ctx()
            total_light_states += 1
        except IndexError:
            break
    return total_light_states


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
time.sleep(0.5)
# make the image and light state watchers share a mock context (fake websocket)
ctx = MockContext()
image_watcher = station.get_delegate("image_watcher")['obj']
light_watcher = station.get_delegate("light_watcher")['obj']
image_watcher.sensors['image_watch'].mock_context = ctx
light_watcher.sensors['light_watch'].mock_context = ctx
# create a mock YAMCS server attached to that shared context
print("initializing mock YAMCS server")
SERVER = make_mock_server(ctx)

try:
    # send some mock image publications
    MAX_PRODUCTS = 40
    SERVER.parameters = [p for p in PARAMETERS if "Images" in p]
    print("spooling mock image publications...", end="\n")
    n_products = serve_images(MAX_PRODUCTS, SERVER)
    print(f"spooled {n_products} image publications")
    waiting, unwait = timeout_factory(timeout=100)
    n_completed = len(station.inbox.completed)
    # send some mock light states
    SERVER.parameters = [p for p in PARAMETERS if "Light" in p]
    print(f"spooled {serve_light_states(SERVER)} light states")

    def n_incomplete():
        return len(
            [n for n in station.tasks.values() if n["status"] != "success"]
        )

    while (n_completed < n_products * 2) or (n_incomplete() > 0):
        duration = waiting()
        if station.state == "crashed":
            raise EnvironmentError("station crashed")
        n_completed = len(station.inbox.completed)
        print(
            f"{n_completed} tasks complete; " f"{n_incomplete()} tasks queued"
        )
        time.sleep(1)
    print("done", n_completed, n_completed)
    time.sleep(0.25)  # make sure last db insert had time to complete
    selector = select(ImageRecord)
    with OSession() as session:
        scalars = session.scalars(selector)
        products = scalars.all()
    assert len(products) == n_products
    prod = products[0]
    print(prod.asdict())
finally:
    station.shutdown()
    SERVER.ctx.kill()
