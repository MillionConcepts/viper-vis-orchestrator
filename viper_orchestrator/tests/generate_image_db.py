"""
simple integration test for raw product creation based on parameters
published by a mock yamcs server.
"""
import shutil
import time

from sqlalchemy import select

from hostess.utilities import timeout_factory
from viper_orchestrator.db import OSession
from viper_orchestrator.db.config import TEST_DB_PATH, DATA_ROOT, BROWSE_ROOT
import viper_orchestrator.station.definition as vsd
from viper_orchestrator.tests.utilities import make_mock_server
from vipersci.vis.db.image_records import ImageRecord

# clean up, start fresh
shutil.rmtree(TEST_DB_PATH, ignore_errors=True)
for folder in (DATA_ROOT, BROWSE_ROOT):
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
station = vsd.create_station()
vsd.launch_delegates(station)
station.save_port_to_shared_memory()
station.start()
# give delegate configuration a moment to propagate
time.sleep(0.5)
# create a mock YAMCS server attached to the parameter-watching delegate
print("initializing mock YAMCS server")
server = make_mock_server(station.get_delegate("watcher")["obj"])
try:
    # send some mock events
    max_products, total_products = 40, 0
    print("spooling mock YAMCS publications...", end="\n")
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
    print(f"spooled {total_products} publications")
    waiting, unwait = timeout_factory(timeout=100)
    n_completed = len(station.inbox.completed)

    def n_incomplete():
        return len(
            [n for n in station.tasks.values() if n["status"] != "success"]
        )

    while (n_completed < total_products * 2) or (n_incomplete() > 0):
        duration = waiting()
        if station.state == "crashed":
            raise EnvironmentError("station crashed")
        n_completed = len(station.inbox.completed)
        print(
            f"{n_completed} tasks complete; " f"{n_incomplete()} tasks queued"
        )
        time.sleep(1)
    print("done", n_completed, total_products)
    time.sleep(0.25)  # make sure last db insert had time to complete
    selector = select(ImageRecord)
    with OSession() as session:
        scalars = session.scalars(selector)
        products = scalars.all()
    assert len(products) == total_products
    prod = products[0]
    print(prod.asdict())
finally:
    station.shutdown()
    server.ctx.kill()
