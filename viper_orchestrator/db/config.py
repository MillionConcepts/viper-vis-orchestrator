from pathlib import Path

from vipersci.vis.db.image_records import ImageRecord

from viper_orchestrator.visintent.tracking.tables import AppBase

BASES = [AppBase, ImageRecord]
TEST_DB_PATH = (Path(__file__).parent / 'vis_db_test.sqlite3').absolute()
TEST = True

# where are we writing our scratch products? for dev, should match MEDIA_ROOT
# in visintent.visintent.settings
# TODO: replace this with the real output path
DATA_ROOT = Path(__file__).parent.parent / "media/products/data/"
BROWSE_ROOT = Path(__file__).parent.parent / "media/products/browse/"
