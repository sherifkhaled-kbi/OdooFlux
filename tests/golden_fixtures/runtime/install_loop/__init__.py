from . import models


def post_init(env):
    # Deliberate non-terminating install step: the runtime adapter must kill the container at its wall-time limit.
    while True:
        pass
