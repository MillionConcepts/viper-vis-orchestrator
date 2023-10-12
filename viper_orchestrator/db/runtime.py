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

from sqlalchemy import create_engine, select, insert
from sqlalchemy.orm import Session

from hostess.subutils import Viewer
from viper_orchestrator.config import BASES, TEST, TEST_DB_PATH, DB_PATH
from vipersci.vis.db.image_tags import ImageTag, taglist

# managed processes that we will clean up on interpreter exit
KILL_TARGETS = []


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
# mission coordinate system center
SPATIAL_REF_VALUES = f"( 910101, 'ROVER', 910101, '+proj=stere +lat_0={LAT_0} +lon_0={LON_0} +R={LUNAR_RADIUS} +units=m')"
# commands to initialize new postgres database
INIT_COMMANDS = (
    f"initdb -D {DB_PATH}",
    f"postgres -D {DB_PATH}",
    f'psql -d {DB_PATH.name} -c "CREATE EXTENSION postgis"',
    f"""psql -d {DB_PATH.name} -c "INSERT into spatial_ref_sys (srid, auth_name, auth_srid, proj4text) values {SPATIAL_REF_VALUES}\"""",
)


def construct_postgres_error(viewer, text="postgres server failed init"):
    return PostgresInitError(
        f"{text}\ncommand {viewer.command} failed:\n\n{','.join(viewer.err)}"
    )


def kill_init_and_delete_db_if_test(viewer):
    viewer.kill()
    if TEST is True:
        # this gets called if the database appears mangled...but we still
        # don't want to autodelete it in prod!
        print('removing db path')
        shutil.rmtree(TEST_DB_PATH)


# if the database doesn't exist at all, create and configure it
if not Path(DB_PATH).exists():
    try:
        DB_PATH.mkdir(exist_ok=True, parents=True)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"database path {DB_PATH} does not exist and cannot be constructed"
        )
    except PermissionError as pe:
        raise PermissionError(
            f"database path {DB_PATH} does not exist and this process lacks "
            f"write permissions to its parent(s): {pe}"
        )
    for cmd in INIT_COMMANDS:
        pginit = Viewer.from_command(cmd)
        if cmd.startswith("postgres -D"):
            time.sleep(1)  # TODO: replace with explicit connection check
            if "system is ready to accept connections" not in pginit.err[-1]:
                kill_init_and_delete_db_if_test(pginit)
            else:
                pginit.wait()
                if pginit.returncode() != 0:
                    kill_init_and_delete_db_if_test(pginit)
                    raise construct_postgres_error(
                        pginit, "server failed launch"
                    )
        # if we start the server ourselves, kill it on exit
        KILL_TARGETS.append(pginit)
        # edit conf file to ensure timezone is set to UTC
        text = (DB_PATH / "postgresql.conf").open().read()
        text = re.sub("\ntimezone.*?\n", "\ntimezone = 'UTC'\n", text)
        with (DB_PATH / "postgresql.conf").open('w') as stream:
            stream.write(text)
# if the database exists, just try to connect to it
else:
    # launch it if it's not running
    pginit = Viewer.from_command(f"postgres -D {DB_PATH}")
    time.sleep(1)
    if "system is ready to accept connections" not in pginit.err[-1]:
        # if it fails with an "another server might be running" message,
        # assume we already launched it on purpose, nbd
        if not re.match(r'.*FATAL:.*lock file "postmaster', pginit.err[0]):
            pginit.kill()
            raise construct_postgres_error(pginit, 'server failed launch')
    else:
        # and if we're launching it here, this is now the process owner,
        # as above; kill it on exit
        KILL_TARGETS.append(pginit)

# shared sqlalchemy Engine for application
ENGINE = create_engine(f"postgresql:///{DB_PATH.name}")

# initialize tables in case they don't exist (operation is harmless if they do)
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
