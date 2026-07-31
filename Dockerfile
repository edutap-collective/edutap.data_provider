# Two stages: build installs the package, the runtime image carries only the result.
# Plain `pip install` on purpose — `uv` belongs in the development environment, not
# in a container image.
FROM python:3.14-slim AS build
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.14-slim
# The interpreter of the base image is 3.14, so this is where `pip install` put the
# package in the build stage. Changing the base image tag means changing this path.
COPY --from=build /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
RUN useradd --create-home --uid 10001 app
WORKDIR /app
USER app
EXPOSE 8000
# --factory: the application is built by create_app(), not exposed as a module-level
# object, so that settings are read when the process starts rather than on import.
CMD ["uvicorn", "edutap.data_provider.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
