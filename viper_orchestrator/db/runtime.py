"""
'singleton' module for setting up or connecting to orchestrator db. 
should be imported if and only if you wish to execute the database
initialization and connection workflow. This module's ENGINE member is
intended for use as a database connection.
"""
import csv
from pathlib import Path
import re

from invoke import UnexpectedExit
from sqlalchemy import create_engine, select, insert
from sqlalchemy.orm import Session

from hostess.subutils import Viewer, run
from hostess.utilities import timeout_factory
from viper_orchestrator.config import BASES, DB_ROOT
from vipersci.vis.db.image_tags import ImageTag, taglist
from vipersci.vis.db.ldst import LDST


class PostgresServerError(OSError):
    pass


class SelectivePostgresShutdown:

    def maybe_shut_down_postgres(self):
        if self.active is True:
            try:
                run(f"pg_ctl stop -D {DB_ROOT}")
            except UnexpectedExit:
                # KeyboardInterrupt will typically propagate
                # to the postgres process via the Viewer,
                # making this unnecessary
                pass

    active = False


SHUTDOWN = SelectivePostgresShutdown()
MANAGED_PROCESSES = []

# coordinate system center
LAT_0, LON_0 = -85.42088, 31.6218
# canonical lunar radius
LUNAR_RADIUS = 1737400
# mission coordinate system center
SPATIAL_REF_VALUES = f"( 910101, 'ROVER', 910101, '+proj=stere +lat_0={LAT_0} +lon_0={LON_0} +R={LUNAR_RADIUS} +units=m')"
# commands to initialize new postgres database
INIT_COMMANDS = (
    f"initdb -D {DB_ROOT}",
    f"postgres -D {DB_ROOT}",
    f'psql -d postgres -c "CREATE EXTENSION postgis"',
    f"""psql -d postgres -c "INSERT into spatial_ref_sys (srid, auth_name, auth_srid, proj4text) values {SPATIAL_REF_VALUES}\"""",
)


def construct_postgres_error(viewer, text="postgres server failed init"):
    return PostgresServerError(
        f"{text}\ncommand {viewer.command} failed:\n\n{','.join(viewer.err)}"
    )


def run_postgres_command(command, initializing=False) -> Viewer:
    """
    run a managed postgres command, waiting and validating output as
    appropriate.
    """
    process = Viewer.from_command(command)
    waiting, _ = timeout_factory(True, 5)
    while True:
        try:
            waiting()
            try:
                process.wait_for_output(0.1)
            except TimeoutError("timed out"):
                continue
            if command.startswith("postgres -D"):
                if "system is ready to accept" in process.err[-1]:
                    MANAGED_PROCESSES.append(process)
                    # if we're launching it here, provide option to shut down
                    # postgres on exit
                    SHUTDOWN.active = True
                    return process
                if re.match(
                    r'.*FATAL:.*lock file "postmaster', process.err[0]
                ):
                    # if it fails with an "another server might be running"
                    # message and we're _not_ in the initialization workflow,
                    # assume we already launched it on purpose.
                    if initializing is True:
                        raise construct_postgres_error(
                            process,
                            "server is already running during initialization; "
                            "something is wrong",
                        )
                    process.kill()
                    return process
                elif process.done:
                    raise PostgresServerError(
                        f"server stopped unexpectedly (code "
                        f"{process.returncode()})"
                    )
            if process.done and process.returncode() != 0:
                raise PostgresServerError(f"error {process.returncode()}")
            elif process.done:
                return process
        except (TimeoutError, PostgresServerError) as err:
            process.kill()
            raise construct_postgres_error(
                process, f"server initialization failed ({err})"
            )


# if the database doesn't exist at all, create and configure it
if not Path(DB_ROOT / "postgresql.conf").exists():
    try:
        DB_ROOT.mkdir(exist_ok=True, parents=True)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"database path {DB_ROOT} does not exist and cannot be constructed"
        )
    except PermissionError as pe:
        raise PermissionError(
            f"database path {DB_ROOT} does not exist and this process lacks "
            f"write permissions to its parent(s): {pe}"
        )
    for cmd in INIT_COMMANDS:
        run_postgres_command(cmd, initializing=True)
        if cmd.startswith("initdb"):
            # edit conf file to ensure timezone is set to UTC
            text = (DB_ROOT / "postgresql.conf").open().read()
            text = re.sub("\ntimezone.*?\n", "\ntimezone = 'UTC'\n", text)
            with (DB_ROOT / "postgresql.conf").open("w") as stream:
                stream.write(text)
        # if we start the server ourselves, provide option to terminate it
        SHUTDOWN.active = True
# if the database exists, just try to connect to it
else:
    # TODO: check and make sure time is set to UTC
    # launch postgres server if it's not running
    pginit = run_postgres_command(f"postgres -D {DB_ROOT}")
# shared sqlalchemy Engine for application
ENGINE = create_engine("postgresql:///postgres")


# initialize tables in case they don't exist (operation is harmless if they do)
for base in BASES:
    base.metadata.create_all(ENGINE)


# initialize pseudo-enums from configuration file
# NOTE: semi-vendored from init function in science repo. it must exactly copy
# this 'official' code and should not be changed.
# TODO: add license note
def set_up_tags_and_hypotheses():
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
        # TODO: this probably isn't how they're going to be initialized later
        ldst_file = Path(__file__).parent / "ldst_data.csv"
        ldst_rows = []
        with ldst_file.open() as lf:
            ldst_text = lf.readlines()
        reader = csv.reader(ldst_text, delimiter=";")
        next(reader)  # Skip first line.
        next(reader)  # Skip second line.
        for row in reader:
            ldst_rows.append(row)
        scalars = session.scalars(select(LDST))
        results = scalars.all()
        if len(results) == 0:
            session.execute(
                insert(LDST),
                [{"id": x, "description": y} for (x, y) in ldst_rows]
            )
            session.commit()
        elif len(results) == len(ldst_rows):
            for i, row in enumerate(results):
                if row.id != ldst_rows[i][0] or row.description != \
                        ldst_rows[i][1]:
                    raise ValueError(
                        f"Row {i} in the database has these values: {row} "
                        f"but should have {ldst_rows[i]}"
                    )
        else:
            raise ValueError(
                f"The {LDST.__tablename__} table already contains the "
                f"following {len(results)} entries: {results}, but should "
                f"contain {len(ldst_rows)} entries."
            )


set_up_tags_and_hypotheses()
