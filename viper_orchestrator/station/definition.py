from pathlib import Path
import random

from viper_orchestrator.db.config import DATA_ROOT
from hostess.station.actors import InstructionFromInfo
from hostess.station.station import Station

from viper_orchestrator.station.actors import (
    InsertIntoDatabase,
    thumbnail_instruction,
    process_image_instruction,
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
    station.process_image_target_name = "processor"
    station.process_image_instruction_maker = process_image_instruction
    station.process_image_criteria = (
        lambda msg: msg["event_type"] == "image_published",
    )
    # add an Actor that inserts ImageRecord objects (or conceivably anything
    # else) into the database
    station.add_element(InsertIntoDatabase)
    # add an Actor that watches to see when the image_processor delegate writes
    # a new TIFF file to disk (this could probably just be replaced with an
    # action upon receiving a completion message)
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
    # raw product-making delegate
    station.launch_delegate(
        "processor",
        elements=(("viper_orchestrator.station.actors", "ImageProcessor"),),
        **DELKWARGS,
    )
    # parameter-watching delegate
    station.launch_delegate(
        "watcher",
        elements=(("viper_orchestrator.station.actors", "ParameterSensor"),),
        # has to be local to use the mock server correctly
        **DELKWARGS | {"context": "local"},
    )
    # tiff-write-watching delegate
    station.launch_delegate(
        "thumbnail_watcher", **thumbnail_watch_launch_spec, **DELKWARGS
    )
    station.launch_delegate("thumbnail", **thumbnail_launch_spec, **DELKWARGS)
    station.set_delegate_properties(
        "watcher",
        parameter_watch_mock=True,
        parameter_watch_parameters=IMAGE_DATA_PARAMETERS,
    )
    station.set_delegate_properties(
        "processor", image_processor_outdir=DATA_ROOT
    )
    station.set_delegate_properties(
        "thumbnail_watcher", **thumbnail_watch_config_spec
    )
    # no special properties to set for the thumbnailer


IMAGE_DATA_PARAMETERS = (
    "/ViperGround/Images/ImageData/Hazcam_front_left_icer",
    "/ViperGround/Images/ImageData/Hazcam_front_right_icer",
    "/ViperGround/Images/ImageData/Hazcam_back_left_icer",
    "/ViperGround/Images/ImageData/Hazcam_back_right_icer",
    "/ViperGround/Images/ImageData/Navcam_left_icer",
    "/ViperGround/Images/ImageData/Navcam_right_icer",
    "/ViperGround/Images/ImageData/Aftcam_left_icer",
    "/ViperGround/Images/ImageData/Aftcam_right_icer",
)
