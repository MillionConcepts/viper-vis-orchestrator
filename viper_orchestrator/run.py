"""simple run hook for testing. prod run hooks may be similar, or not."""
import os
import shutil
import time

from hostess.subutils import Viewer
from viper_orchestrator.config import TEST_DB_PATH, MEDIA_ROOT, ROOTS
import viper_orchestrator.station.definition as vsd

# STUFF FOR TEST
shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
shutil.rmtree(TEST_DB_PATH, ignore_errors=True)
for folder in ROOTS:
    folder.mkdir(parents=True, exist_ok=True)
try:
    os.unlink("../logs/lightstate.csv")
except FileNotFoundError:
    pass
PROCESSOR_PATH = ("viper", "replay")

station = vsd.create_station()
station.save_port_to_shared_memory()
try:
    station.start()
    vsd.launch_delegates(station, mock=False, processor_path=PROCESSOR_PATH)
    # we're probably not actually going to execute the django server from this
    # script in prod but whatever
    django_process = Viewer.from_command(
        "/opt/mambaforge/envs/viperdev/bin/python",
        "visintent/manage.py",
        "runserver"
    )
    time.sleep(3)
    print(django_process.out)
    print(django_process.err)
    while True:
        time.sleep(5)
finally:
    station.shutdown()
    try:
        django_process.kill()
    except NameError:
        pass
