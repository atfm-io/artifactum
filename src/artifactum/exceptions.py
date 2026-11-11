class ArtifactumError(Exception):
    """Base exception for all Artifactum errors."""


class ArtifactNotFoundError(ArtifactumError):
    def __init__(self, artifact_id: str):
        self.artifact_id = artifact_id
        super().__init__(f"Artifact not found: {artifact_id}")


class ConfigError(ArtifactumError):
    pass


class AuthError(ArtifactumError):
    pass


class PlanLimitError(ArtifactumError):
    """Publishing is blocked because the plan's artifact limit has been reached."""

    def __init__(self, message: str, upgrade_url: str | None = None):
        self.upgrade_url = upgrade_url
        super().__init__(message)


class StorageError(ArtifactumError):
    """A file couldn't be stored or fetched: the location is missing, unreadable or misconfigured."""
