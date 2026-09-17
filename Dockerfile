# Worldloom Studio, ready to open.
#
# The image installs the built wheel, not the source tree, so what runs here is
# what `pip install "worldloom[all]"` gives anyone else. A build that only works
# against a checkout is not a distribution.
#
#   docker build -t worldloom .
#   docker run --rm -p 127.0.0.1:8765:8765 -v worldloom-workspace:/workspace worldloom
#
# Then open http://127.0.0.1:8765. The workspace volume holds company
# revisions, jobs and datasets; back it up to keep generated corpora.
#
# The container calls no model service. To drive an installed coding harness,
# run the Studio on the host instead: the harness's login lives there.

FROM python:3.12-slim AS build
WORKDIR /src
# Build the wheel here so the build backend never reaches the runtime image.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples
RUN python -m pip install --no-cache-dir build==1.3.0 \
 && python -m build --wheel --outdir /dist

FROM python:3.12-slim
# A non-root user with a writable workspace: the process writes only there.
RUN useradd --create-home --uid 10001 worldloom
COPY --from=build /dist/*.whl /tmp/
# One wheel, one install. The `all` extra pulls the four renderers and the MCP
# server, which is what makes the console able to render a document at all.
RUN wheel="$(ls /tmp/worldloom-*.whl)" \
 && python -m pip install --no-cache-dir "${wheel}[all]" \
 && rm -f /tmp/*.whl \
 && worldloom --help > /dev/null
RUN install -d -o worldloom -g worldloom /workspace
WORKDIR /workspace
USER worldloom
VOLUME ["/workspace"]
EXPOSE 8765

# Bound to every interface because the port is published to the host. The
# console has no authentication, so publish it to 127.0.0.1 and nowhere else.
ENTRYPOINT ["worldloom"]
CMD ["studio", "serve", "--workspace", "/workspace", "--port", "8765", "--host", "0.0.0.0"]
