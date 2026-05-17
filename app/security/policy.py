from __future__ import annotations

from app.core.config import Settings
from app.domain.entities.rag import RetrievalCandidate
from app.domain.errors import ForbiddenError


class SecurityPolicyService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def enforce_chat_sensitivity_policy(
        self,
        *,
        model_profile: str,
        selected_sources: list[RetrievalCandidate],
    ) -> None:
        if not selected_sources:
            return
        highest_sensitivity = _highest_sensitivity(candidate.sensitivity for candidate in selected_sources)
        if highest_sensitivity != "restricted":
            return
        if model_profile not in self.settings.restricted_profiles_set:
            raise ForbiddenError(
                "Restricted content requires an approved model profile.",
                details={"required_profiles": sorted(self.settings.restricted_profiles_set)},
            )
        chain = self.settings.profile_targets(model_profile)
        disallowed = sorted({target.provider for target in chain if target.provider not in self.settings.restricted_provider_set})
        if disallowed:
            raise ForbiddenError(
                "Restricted content cannot be sent to the configured providers for this profile.",
                details={
                    "profile": model_profile,
                    "disallowed_providers": disallowed,
                    "allowed_providers": sorted(self.settings.restricted_provider_set),
                },
            )


def _highest_sensitivity(values) -> str:
    ordered = {"public": 1, "internal": 2, "confidential": 3, "restricted": 4}
    highest = "public"
    highest_rank = 1
    for value in values:
        rank = ordered.get(value, 2)
        if rank > highest_rank:
            highest_rank = rank
            highest = value
    return highest
