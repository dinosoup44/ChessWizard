"""Pure pre-import version/dependency admission; app and API versions are independent."""
import sys
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version
from chesswizard_plugin_api import API_VERSION
from chesswizard_version import VERSION
from plugin_models import CompatibilityCode, HostVersions


def current_versions() -> HostVersions:
    """Describe the current core contract independently of plugin metadata.

    Returns:
        Application, SDK, and interpreter versions.
    """
    return HostVersions(VERSION, API_VERSION, ".".join(map(str, sys.version_info[:3])))


def assess_compatibility(required_api: str, minimum_app: str, python_requirement: str,
                         dependencies: tuple[str, ...], host: HostVersions) -> tuple[CompatibilityCode, str]:
    """Evaluate declarative compatibility without importing plugin implementation.

    Args:
        required_api: Minimum API version declared by the manifest.
        minimum_app: Minimum application version.
        python_requirement: Distribution Python specifier.
        dependencies: Distribution requirement declarations.
        host: Explicit host versions for reproducible upgrade checks.

    Returns:
        Static decision code and core-authored explanation.
    """
    try:
        api, available = Version(required_api), Version(host.api)
        minimum, application = Version(minimum_app), Version(host.application)
        python = Version(host.python)
        requirements = tuple(Requirement(value) for value in dependencies)
        if len(requirements) != 1 or canonicalize_name(requirements[0].name) != "chesswizard-plugin-api":
            return CompatibilityCode.DEPENDENCY, "Only the public SDK dependency is supported"
        dependency = requirements[0]
        if dependency.url or dependency.extras or dependency.marker or available not in dependency.specifier:
            return CompatibilityCode.DEPENDENCY, "Unsupported SDK dependency contract"
        if api.major != available.major or api > available:
            return CompatibilityCode.API, "Unsupported plugin API version"
        if minimum > application:
            return CompatibilityCode.APP, "Minimum ChessWizard version unmet"
        if not python_requirement or python not in SpecifierSet(python_requirement):
            return CompatibilityCode.PYTHON, "Unsupported Python version"
        return CompatibilityCode.COMPATIBLE, ""
    except (ValueError, TypeError):
        return CompatibilityCode.METADATA, "Invalid version or dependency metadata"
