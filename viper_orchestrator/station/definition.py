from pathlib import Path
import random

from viper_orchestrator.db.config import DATA_ROOT, PARAMETERS_OF_INTEREST
from hostess.station.actors import InstructionFromInfo
from hostess.station.station import Station

from viper_orchestrator.station.actors import (
    InsertIntoDatabase,
    thumbnail_instruction,
    process_image_instruction,
    process_light_state_instruction,
)

# basic settings for delegates in this application
DELKWARGS = {"update_interval": 0.1, "context": "local", "n_threads": 4}


def create_station():
    """creates the station"""
    host, port = "localhost", random.randint(10000, 20000)
    station = Station(host, port, n_threads=12)
    # add an Actor that creates instructions to make image products when it
    # receives an Info message about a new image
    station.add_element(InstructionFromInfo, name="process_image")
    station.process_image_target_name = "image_processor"
    station.process_image_instruction_maker = process_image_instruction
    station.process_image_criteria = (
        lambda msg: msg["event_type"] == "image_published",
    )
    station.add_element(InstructionFromInfo, name="process_light_state")
    station.process_image_target_name = "light_processor"
    station.process_image_instruction_maker = process_light_state_instruction
    station.process_image_criteria = (
        lambda msg: msg["event_type"] == "light_state_published",
    )
    # add an Actor that inserts SQLAlchemy DeclarativeBase objects
    # (abstractions of table rows into the VIS database)
    station.add_element(InsertIntoDatabase)
    # add an Actor that watches to see when the image_processor Delegate writes
    # a new TIFF file to disk
    thumbnail_checker = InstructionFromInfo
    station.add_element(thumbnail_checker, name="thumbnail")
    # add an Actor that creates instructions to make thumbnails when we hear
    # about a new TIFF file
    station.thumbnail_instruction_maker = thumbnail_instruction
    station.thumbnail_criteria = [lambda n: Path(n["content"]).is_file()]
    station.thumbnail_target_name = "thumbnail"
    return station


def launch_delegates(station):
    """defines, launches, and queues config instructions for delegates"""
    thumbnail_watch_launch_spec = {
        # add a directory-watching Sensor
        "elements": [("hostess.station.actors", "DirWatch")],
    }
    thumbnail_watch_config_spec = {
        # what directory shall we watch?
        "dirwatch_target": DATA_ROOT,
        # what filename patterns are we watching for?
        "dirwatch_patterns": (r".*\.tif",),
    }
    # thumbnail-making delegate
    thumbnail_launch_spec = {
        "elements": [("hostess.station.actors", "FuncCaller")]
    }
    # create_image.create()-handling delegate
    station.launch_delegate(
        "image_processor",
        elements=(("viper_orchestrator.station.actors", "ImageProcessor"),),
        **DELKWARGS,
    )
    # LightRecord-making delegate
    station.launch_delegate(
        "light_state_processor",
        elements=(
            ("viper_orchestrator.station.actors", "LightStateProcessor"),
        ),
        **DELKWARGS,
    )
    # parameter-watching delegate. note that to work correctly in mock mode,
    # this should always be local so that it can interact with the
    # locally-instantiated MockServer.
    station.launch_delegate(
        "parameter_watcher",
        elements=(("viper_orchestrator.station.actors", "ParameterSensor"),),
        **DELKWARGS | {"context": "local"},
    )
    # tiff-write-watching delegate
    station.launch_delegate(
        "thumbnail_watcher", **thumbnail_watch_launch_spec, **DELKWARGS
    )
    station.launch_delegate("thumbnail", **thumbnail_launch_spec, **DELKWARGS)
    station.set_delegate_properties(
        "parameter_watcher",
        parameter_watch_mock=True,
        parameter_watch_parameters=PARAMETERS_OF_INTEREST
    )
    station.set_delegate_properties(
        "image_processor", image_processor_outdir=DATA_ROOT
    )
    station.set_delegate_properties(
        "thumbnail_watcher", **thumbnail_watch_config_spec
    )
    # no special properties to set for the thumbnailer or LightRecord maker
