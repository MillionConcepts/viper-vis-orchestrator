"""utility tables for persisting orchestrator state."""
from sqlalchemy import Column, DateTime, Table, Integer
from sqlalchemy.orm import mapper, declarative_base

# parameters we care about.
PARAMETERS_OF_INTEREST = (
    '/ViperGround/Images/ImageData/Hazcam_back_left_icer',
    '/ViperGround/Images/ImageData/Hazcam_back_right_icer',
    '/ViperGround/Images/ImageData/Hazcam_front_left_icer',
    '/ViperGround/Images/ImageData/Hazcam_front_right_icer',
    "/ViperGround/Images/ImageData/Navcam_left_icer",
    "/ViperGround/Images/ImageData/Navcam_right_icer",
    "/ViperGround/Images/ImageData/Aftcam_left_icer",
    "/ViperGround/Images/ImageData/Aftcam_right_icer",
    "/ViperRover/LightsControl/state"
)
UtilityBase = declarative_base()


def make_last_time_table_class():
    definition = {
        "__tablename__": "last_time",
                     "pk": Column(name="pk", type_=Integer, primary_key=True)
    } | {
        param.replace("/", "_"): Column(
            name=param.replace("/", "_"), type_=DateTime(timezone=True)
        )
        for param in PARAMETERS_OF_INTEREST
    }
    return type("LastTime", (UtilityBase,), definition)


LastTime = make_last_time_table_class()
