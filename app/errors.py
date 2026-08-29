class LinkError(Exception):
    """Base exception for safe client-visible link errors."""


class LinkConflict(LinkError):
    pass


class LinkNotFound(LinkError):
    pass


class LinkGone(LinkError):
    pass
