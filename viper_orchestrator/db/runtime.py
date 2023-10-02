"""
'singleton' module for setting up or connecting to orchestrator db. 
should be imported if and only if you wish to execute the database
initialization and connection workflow. This module's ENGINE member is
intended for use as a database connection.
"""
import atexit
import re
import shutil
import time
from functools import partial
from pathlib import Path

from hostess.subutils import Viewer
from sqlalchemy import create_engine, select, insert
from sqlalchemy.orm import Session

from viper_orchestrator.db.config import BASES, TEST, TEST_DB_PATH
from vipersci.vis.db.image_tags import ImageTag, taglist

# lists defining managed processes that we will, respectively, clean up and
# not clean up  on interpreter exit
KILL_TARGETS = []
DO_NOT_KILL = []


def listkiller(processes: list[Viewer]):
    if len(processes) > 0:
        print('killing managed processes on exit...')
    while len(processes) > 0:
        viewer = processes.pop()
        print(f"killing PID {viewer.pid} ({viewer.command})...", end="")
        viewer.kill()
        viewer.wait()
        print(f"killed")


atexit.register(partial(listkiller, KILL_TARGETS))


class PostgresInitError(OSError):
    pass


# coordinate system center
LAT_0, LON_0 = -85.42088, 31.6218
# canonical lunar radius
LUNAR_RADIUS = 1737400
# commands to initialize new postgres server
SPATIAL_REF_VALUES = f"( 910101, 'ROVER', 910101, '+proj=stere +lat_0={LAT_0} +lon_0={LON_0} +R={LUNAR_RADIUS} +units=m')"
INIT_COMMANDS = (
    f"initdb -D {TEST_DB_PATH}",
    f"postgres -D {TEST_DB_PATH}",
    f'psql -d {TEST_DB_PATH.name} -c "CREATE EXTENSION postgis"',
    f"""psql -d {TEST_DB_PATH.name} -c "INSERT into spatial_ref_sys (srid, auth_name, auth_srid, proj4text) values {SPATIAL_REF_VALUES}\"""",
)


def construct_postgres_error(viewer, text="postgres server failed init"):
    return PostgresInitError(
        f"{text}\ncommand {viewer.command} failed:\n\n{','.join(viewer.err)}"
    )


def kill_and_delete(viewer):
    viewer.kill()
    print('removing db path')
    shutil.rmtree(TEST_DB_PATH)


if TEST is True:
    # initialize the test database if it doesn't exist
    if not Path(TEST_DB_PATH).exists():
        for cmd in INIT_COMMANDS:
            pginit = Viewer.from_command(cmd)
            if cmd.startswith("postgres -D"):
                time.sleep(1)  # TODO: replace with explicit connection check
                if "system is ready to accept connections" not in pginit.err[-1]:
                    kill_and_delete(pginit)
                    raise construct_postgres_error(
                        pginit, "server failed launch"
                    )
                KILL_TARGETS.append(pginit)
            else:
                pginit.wait()
                if pginit.returncode() != 0:
                    kill_and_delete(pginit)
                    raise construct_postgres_error(pginit)
            # edit conf file to ensure timezone is set to UTC
            text = (TEST_DB_PATH / "postgresql.conf").open().read()
            text = re.sub("\ntimezone.*?\n", "\ntimezone = 'UTC'\n", text)
            with (TEST_DB_PATH / "postgresql.conf").open('w') as stream:
                stream.write(text)
    # otherwise, simply connect to the test database
    else:
        pginit = Viewer.from_command(f"postgres -D {TEST_DB_PATH}")
        time.sleep(1)
        if "system is ready to accept connections" not in pginit.err[-1]:
            # if it fails with the "another server might be running" message,
            # assume we already launched it on purpose. i.e., don't kill it
            # when we leave...
            if "another server might be running" not in pginit.stderr[0]:
                pginit.kill()
                raise construct_postgres_error(pginit, 'server failed launch')
            # ...but make sure we can still access it if we like.
            DO_NOT_KILL.append(pginit)
        else:
            KILL_TARGETS.append(pginit)
    ENGINE = create_engine(f"postgresql:///{TEST_DB_PATH.name}")
else:
    # code for connecting to the system-level postgresql server, whose
    # parameters are not yet defined, goes here
    raise NotImplementedError

# TODO: this should be harmless, make sure it is
for base in BASES:
    base.metadata.create_all(ENGINE)


# initialize pseudo-enum from configuration file
# NOTE: semi-vendored from init functions in science repo. it must exactly copy 
# this 'official' code and should not be changed.
# TODO: add license note
def set_up_tags():
    with Session(ENGINE) as session:
        # Establish image_tags
        scalars = session.scalars(select(ImageTag))
        results = scalars.all()
        if len(results) == 0:
            session.execute(insert(ImageTag), [{"name": x} for x in taglist])
            session.commit()
        elif len(results) == len(taglist):
            for i, row in enumerate(results):
                if row.name != taglist[i]:
                    raise ValueError(
                        f"Row {i} in the database has id {row.id} and tag "
                        f"{row.name} but should have {taglist[i]} from "
                        f"{taglist}."
                    )
        else:
            raise ValueError(
                f"The {ImageTag.__tablename__} table already contains the "
                f"following {len(results)} entries: "
                f"{[r.name for r in results]}, but should "
                f"contain these {len(taglist)} entries: {taglist}"
            )


set_up_tags()
