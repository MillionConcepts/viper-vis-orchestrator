Repository for VIPER VIS orchestrator / request frontend code.

# Installation

1. Install dependencies from the environment.yml file using `conda` or 
`mamba`.
2. Install `yamcs-client` from PyPi using `pip` with the `--no-deps` flag (to 
avoid unnecessary installation of an old `protobuf` version).
3. Install `vipersci` and `hostess` from source. We recommend installing 
`vipersci` with the `--no-deps` flag in order to avoid adding expensive 
dependencies not currently used in VIS workflows (e.g. `rasterio`).
4. install `viper_orchestrator` using the stub setup.py file (`pip install -e . setup.py`).

Use of this module's full functionality requires sample data files that are too large 
to include here and are moreover subject to VIPER mission confidentiality restrictions.
If you are authorized for access to these files and require them, please contact Michael 
(mstclair@millionconcepts.com) for details.

# Contents

## db
Database configuration, setup, and access.

## station
Structure definitions, configuration, and helper functions for the 'backend'
components of the orchestrator, i.e., the orchestrator proper, designed to
parse YAMCS events (or other triggers, internal or external) and execute 
various processes in response.

## tests
Tests and supporting utilities. All tests are currently 
end-to-end / integration tests, and conveniently generate database tables 
inline that can be used for user testing and development.

## visintent
A Django application that implements the 'frontend' 
components of the orchestrator, i.e., CRUD functionality for 
intents/requests and protected list entries, as well as image browsing.

### visintent/visintent
Mostly Django boilerplate. Will contain environment-specific configuration
in prod, once that is hammered out.

### visintent/tracking
The business end of the frontend application. Includes SQLAlchemy definitions for 
tables managed by the orchestrator, along with conventional Django URL 
routing config, view functions, form definitions, and HTML templates.

## yamcsutils
Utilities for executing, controlling, and interpreting locally-running instances of 
the `yamcs` server. This module is intended to quickly and efficiently generate
test data. In order to facilitate this, it operates the `yamcs` server in an unusual
and unstable configuration. This code should absolutely not be used in production.

## mock_data
Stub folder for mock data files not included in repository.

# Caveats
Note that if you wish to recreate sample events (or produce new ones from a 
new sample data file), running the `yamcs` server in a Python-managed thread is _touchy_. 
If it crashes, or if you stop it with SIGKILL rather than SIGTERM, it can 
leave temp files around that make its HTTP frontend not work for reasons.
