---
name: ship
description: Generate a Dockerfile and docker-compose.yml to package the agent for deployment.
---

# Ship Stage Instructions

You have been invoked to run the `*ship` ADL stage.
This stage generates production deployment artifacts for the Mutagent system.

1. Execute the `python scripts/ship.py` script.
2. Read the output of the script to verify the Dockerfiles were created successfully.
3. Inform the user that the packaging step is complete and they can now run `docker-compose up --build`.
