from pathlib import Path

from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.image_stats import ImageStats
from vipersci.vis.db.image_tags import ImageTag
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST
from vipersci.vis.db.ldst import LDST
from vipersci.vis.db.ldst_verification import LDSTVerification
from vipersci.vis.db.light_records import LightRecord

# parameters we know we care about at the moment.
PARAMETERS_OF_INTEREST = (
    "/ViperGround/Images/ImageData/Hazcam_back_left_icer",
    "/ViperGround/Images/ImageData/Hazcam_back_right_icer",
    "/ViperGround/Images/ImageData/Hazcam_front_left_icer",
    "/ViperGround/Images/ImageData/Hazcam_front_right_icer",
    "/ViperGround/Images/ImageData/Navcam_left_icer",
    "/ViperGround/Images/ImageData/Navcam_right_icer",
    "/ViperGround/Images/ImageData/Aftcam_left_icer",
    "/ViperGround/Images/ImageData/Aftcam_right_icer",
    "/ViperRover/LightsControl/state",
)

BASES = [
    ImageRecord,
    ImageRequest,
    ImageStats,
    ImageTag,
    JuncImageRecordTag,
    JuncImageRequestLDST,
    LDST,
    LDSTVerification,
    LightRecord,
    ProtectedListEntry,
]

# TODO: add PROD_DB_PATH based on gunicorn/nginx/docker config
TEST_DB_PATH = (Path(__file__).parent / 'postgres').absolute()
TEST = True

# where are we writing our scratch products? should match MEDIA_ROOT in
# visintent.visintent.settings
# TODO: add prod paths based on gunicorn/nginx/docker config
DATA_ROOT = Path(__file__).parent.parent / "media/products/data/"
BROWSE_ROOT = Path(__file__).parent.parent / "media/products/browse/"
