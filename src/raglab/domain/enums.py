from enum import StrEnum


class ChunkingStrategy(StrEnum):
    TRADITIONAL = "traditional"
    SLIDE = "slide"
    LATE = "late"


class DistanceMetric(StrEnum):
    COSINE = "cosine"


class IndexStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExperimentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
