"""simple run hook for testing."""
import shutil
import time

from hostess.subutils import Viewer
from viper_orchestrator.config import (
    MEDIA_ROOT,
    ROOTS,
    TEST,
    DB_PATH,
    LIGHTSTATE_LOG_FILE,
)
import viper_orchestrator.station.definition as vsd

# STUFF FOR TEST
if TEST is True:
    shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
    shutil.rmtree(DB_PATH, ignore_errors=True)
    for folder in ROOTS:
        folder.mkdir(parents=True, exist_ok=True)
    LIGHTSTATE_LOG_FILE.unlink(missing_ok=True)

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
        "runserver",
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
