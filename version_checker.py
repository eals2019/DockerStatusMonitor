#!/usr/bin/env python3
"""
Docker Image Version Checker
Checks if running containers have updates available on Docker Hub / GitHub Container Registry.
Only checks containers from docker-compose.yml files in non-numbered project folders.
"""

import subprocess
import json
import re
import os
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# Cache for version check results
_version_cache: Dict[str, dict] = {}
_last_check_time: Optional[datetime] = None
_check_interval = timedelta(hours=24)
_check_lock = threading.Lock()


def get_workspace_root() -> Path:
    """Get the Docker-Containers workspace root."""
    # This script lives in: Docker-Containers/3. Docker Tools/Docker Status Monitor/
    script_dir = Path(__file__).parent
    return script_dir.parent.parent


def find_compose_files() -> List[Path]:
    """
    Find docker-compose.yml files in project folders.
    Excludes:
    - Numbered folders (0. Deleted, 1. Container Notes, 2. Docker Setup Scripts, 3. Docker Tools)
    - Hidden folders
    """
    workspace = get_workspace_root()
    compose_files = []
    
    # Pattern to match numbered folders like "0. ", "1. ", "2. ", etc.
    numbered_folder_pattern = re.compile(r'^\d+\.\s')
    
    for item in workspace.iterdir():
        if not item.is_dir():
            continue
        
        # Skip hidden folders
        if item.name.startswith('.'):
            continue
        
        # Skip numbered folders
        if numbered_folder_pattern.match(item.name):
            continue
        
        # Look for docker-compose.yml in this folder
        compose_file = item / "docker-compose.yml"
        if compose_file.exists():
            compose_files.append(compose_file)
        
        # Also check for docker-compose.yaml
        compose_file_yaml = item / "docker-compose.yaml"
        if compose_file_yaml.exists():
            compose_files.append(compose_file_yaml)
    
    return compose_files


def parse_compose_images(compose_file: Path) -> Dict[str, str]:
    """
    Parse docker-compose.yml to extract service names and their images.
    Returns dict of {service_name: image_name}
    """
    images = {}
    
    try:
        with open(compose_file, 'r') as f:
            content = f.read()
        
        # Simple YAML parsing for image: lines
        # This is a basic parser - could use PyYAML for more robust parsing
        current_service = None
        in_services = False
        services_indent = None  # Will be set when we find first service
        
        for line in content.split('\n'):
            stripped = line.strip()
            
            # Skip empty lines and comments
            if not stripped or stripped.startswith('#'):
                continue
            
            # Track if we're in services section
            if stripped == 'services:':
                in_services = True
                continue
            
            if not in_services:
                continue
            
            # Count leading spaces
            leading_spaces = len(line) - len(line.lstrip())
            
            # Check for service name (line that ends with : and is at service indent level)
            if stripped.endswith(':') and not stripped.startswith('#'):
                # First service defines the indent level (could be 2 or 4 spaces)
                if services_indent is None and leading_spaces > 0:
                    services_indent = leading_spaces
                
                # Service names are at the first indent level after services:
                if services_indent and leading_spaces == services_indent:
                    service_name = stripped.rstrip(':')
                    # Make sure it's not a YAML keyword
                    if not any(keyword == service_name for keyword in ['image', 'build', 'volumes', 'ports', 'environment', 'networks', 'depends_on', 'restart', 'container_name', 'labels', 'command', 'entrypoint', 'version']):
                        current_service = service_name
            
            # Look for image: line
            if 'image:' in stripped and current_service:
                match = re.search(r'image:\s*["\']?([^"\'#\s]+)["\']?', stripped)
                if match:
                    image = match.group(1)
                    # Handle variable substitution like ${VAR:-default}
                    if '${' in image:
                        # Extract default value if present
                        var_match = re.search(r'\$\{[^:}]+:-([^}]+)\}', image)
                        if var_match:
                            image = var_match.group(1)
                        else:
                            # Can't resolve variable, skip
                            continue
                    images[current_service] = image
    
    except Exception as e:
        print(f"Error parsing {compose_file}: {e}")
    
    return images


def get_running_container_images() -> Dict[str, dict]:
    """
    Get currently running containers with their image info.
    Returns dict of {container_name: {image, image_id, created}}
    """
    containers = {}
    
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Image}}|{{.ID}}"],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    name = parts[0]
                    image = parts[1]
                    container_id = parts[2] if len(parts) > 2 else ""
                    
                    # Get image digest
                    digest = get_local_image_digest(image)
                    
                    # Get local image creation date
                    local_created = get_local_image_created(image)
                    
                    containers[name] = {
                        "image": image,
                        "container_id": container_id,
                        "local_digest": digest,
                        "local_created": local_created
                    }
    
    except Exception as e:
        print(f"Error getting running containers: {e}")
    
    return containers


def get_local_image_created(image: str) -> Optional[str]:
    """Get the creation date of a local Docker image."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Created}}", image],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse ISO format date
            created = result.stdout.strip()
            # Return just the date part YYYY-MM-DD
            if 'T' in created:
                return created.split('T')[0]
            return created[:10]
    except:
        pass
    return None


def get_local_image_digest(image: str) -> Optional[str]:
    """Get the digest of a local Docker image."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{index .RepoDigests 0}}", image],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            # Extract just the digest part (after @)
            digest_full = result.stdout.strip()
            if '@' in digest_full:
                return digest_full.split('@')[1]
            return digest_full
    except:
        pass
    return None


def parse_image_name(image: str) -> Tuple[str, str, str]:
    """
    Parse image name into (registry, repository, tag).
    Examples:
    - nginx:latest -> (docker.io, library/nginx, latest)
    - ghcr.io/user/repo:v1 -> (ghcr.io, user/repo, v1)
    - user/image:tag -> (docker.io, user/image, tag)
    """
    # Default values
    registry = "docker.io"
    tag = "latest"
    
    # Split tag
    if ':' in image and '/' in image.split(':')[-1] == False:
        image_part, tag = image.rsplit(':', 1)
    elif ':' in image and '@' not in image:
        # Handle cases like ghcr.io/org/repo:tag
        parts = image.split(':')
        if len(parts) == 2 and '/' in parts[1]:
            # This is registry:port case, no tag
            image_part = image
        else:
            image_part = ':'.join(parts[:-1])
            tag = parts[-1]
    else:
        image_part = image.split('@')[0] if '@' in image else image
    
    # Determine registry
    if '/' in image_part:
        first_part = image_part.split('/')[0]
        if '.' in first_part or ':' in first_part:
            # It's a registry
            registry = first_part
            repository = '/'.join(image_part.split('/')[1:])
        else:
            # It's a user/repo on Docker Hub
            repository = image_part
    else:
        # Official image
        repository = f"library/{image_part}"
    
    return registry, repository, tag


def check_dockerhub_update(repository: str, tag: str, local_digest: Optional[str]) -> Optional[dict]:
    """
    Check Docker Hub for updates to an image using tag-matching approach.
    Matches local digest to Docker Hub tags to determine actual version numbers.
    Returns dict with update info or None if no update/error.
    """
    try:
        # Regex for semantic version tags (v1.2.3, 1.2.3, 2.10.3, 2026.1.1, etc.)
        # Must have at least major.minor to be considered a proper version
        semver_pattern = re.compile(r'^v?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?$')
        
        # Find version tags (exclude latest, edge, etc.)
        version_tags = []
        latest_tag_info = None
        local_version = None
        
        # Search multiple pages to find the local digest's version
        max_pages = 5  # Search up to 500 tags
        page = 1
        next_url = f"https://hub.docker.com/v2/repositories/{repository}/tags?page_size=100"
        
        while next_url and page <= max_pages:
            req = urllib.request.Request(next_url, headers={'User-Agent': 'Docker-Status-Monitor/1.0'})
            
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())
            
            tags_data = data.get('results', [])
            
            for tag_info in tags_data:
                tag_name = tag_info.get('name', '')
                
                # Track the 'latest' tag - use manifest digest for comparison
                if tag_name == 'latest':
                    latest_tag_info = tag_info
                    # Check if latest tag's manifest digest matches local
                    latest_manifest_digest = tag_info.get('digest')
                    if local_digest and latest_manifest_digest == local_digest:
                        # User has the exact latest - will resolve version below
                        pass
                    continue
                
                # Check if this looks like a proper semver tag (x.y or x.y.z)
                match = semver_pattern.match(tag_name)
                if match:
                    # Use the manifest digest (tag_info['digest']) NOT the per-arch digest
                    tag_digest = tag_info.get('digest')
                    
                    parts = [int(p) if p else 0 for p in match.groups() if p is not None]
                    
                    version_tags.append({
                        'name': tag_name,
                        'digest': tag_digest,
                        'version_parts': parts,
                        'last_updated': tag_info.get('last_updated', '')
                    })
                    
                    # Check if this tag's manifest digest matches our local digest
                    if local_digest and tag_digest and local_digest == tag_digest:
                        local_version = tag_name
            
            # If we found the local version, we can stop searching
            if local_version:
                break
            
            # Get next page URL
            next_url = data.get('next')
            page += 1
        
        # Sort version tags by version number (descending)
        version_tags.sort(key=lambda x: x['version_parts'], reverse=True)
        
        # Find the latest version
        latest_version = version_tags[0]['name'] if version_tags else None
        latest_version_updated = version_tags[0]['last_updated'] if version_tags else None
        
        # If we didn't find local version via digest match, check if user's tag is a version
        if not local_version and tag != 'latest':
            if semver_pattern.match(tag):
                local_version = tag
        
        # If we still don't have local version and have latest info, try matching manifest digest
        if not local_version and latest_tag_info:
            # Use manifest digest, not per-architecture digest
            latest_manifest_digest = latest_tag_info.get('digest')
            
            if local_digest and latest_manifest_digest == local_digest:
                # User has the latest version - show the actual version number
                local_version = latest_version if latest_version else 'latest'
        
        # Determine if update is available
        has_update = False
        
        # Check if user has the current :latest tag
        has_current_latest = False
        if latest_tag_info and local_digest:
            latest_manifest_digest = latest_tag_info.get('digest')
            has_current_latest = (latest_manifest_digest == local_digest)
        
        # Different logic depending on whether user is tracking :latest or a pinned version
        if tag == 'latest':
            # User is tracking :latest - only care if :latest tag has changed
            if has_current_latest:
                # User has the current :latest - they're up to date
                has_update = False
                # Show them what version :latest currently is
                if local_version and local_version != 'latest':
                    # We found the version number for their :latest
                    pass
                else:
                    local_version = latest_version if latest_version else 'latest'
            else:
                # User's digest doesn't match current :latest - there's an update
                has_update = True
                if not local_version or local_version == 'latest':
                    local_version = "outdated"
        else:
            # User has a pinned version - compare version numbers
            if local_version and latest_version:
                local_match = semver_pattern.match(local_version)
                latest_match = semver_pattern.match(latest_version)
                
                if local_match and latest_match:
                    local_parts = [int(p) if p else 0 for p in local_match.groups() if p is not None]
                    latest_parts = [int(p) if p else 0 for p in latest_match.groups() if p is not None]
                    
                    # Pad to same length
                    max_len = max(len(local_parts), len(latest_parts))
                    local_parts += [0] * (max_len - len(local_parts))
                    latest_parts += [0] * (max_len - len(latest_parts))
                    
                    has_update = local_parts < latest_parts
        
        if has_update:
            return {
                "has_update": True,
                "local_version": local_version or "unknown",
                "latest_version": latest_version or "unknown",
                "local_digest": local_digest[:16] + "..." if local_digest else "unknown",
                "last_updated": latest_version_updated[:10] if latest_version_updated else "",
                "registry": "Docker Hub",
                "has_current_latest_tag": has_current_latest  # User has :latest but newer version exists
            }
        else:
            return {
                "has_update": False,
                "local_version": local_version or tag,
                "latest_version": latest_version or tag,
                "last_updated": latest_version_updated[:10] if latest_version_updated else "",
                "registry": "Docker Hub"
            }
    
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"error": f"Repository '{repository}' not found on Docker Hub"}
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def check_ghcr_update(repository: str, tag: str, local_digest: Optional[str]) -> Optional[dict]:
    """
    Check GitHub Container Registry for updates.
    Note: This requires authentication for private repos.
    """
    try:
        # GHCR uses OCI distribution API
        # For public images, we can get the manifest
        url = f"https://ghcr.io/v2/{repository}/manifests/{tag}"
        
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Docker-Status-Monitor/1.0',
            'Accept': 'application/vnd.docker.distribution.manifest.v2+json'
        })
        
        with urllib.request.urlopen(req, timeout=10) as response:
            # The digest is often in the Docker-Content-Digest header
            remote_digest = response.headers.get('Docker-Content-Digest', '')
            
            if local_digest and remote_digest:
                if local_digest != remote_digest:
                    return {
                        "has_update": True,
                        "local_digest": local_digest[:16] + "..." if local_digest else "unknown",
                        "remote_digest": remote_digest[:16] + "..." if remote_digest else "unknown",
                        "registry": "GitHub Container Registry"
                    }
            
            return {
                "has_update": False,
                "registry": "GitHub Container Registry"
            }
    
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"error": "Authentication required (private repo?)"}
        elif e.code == 404:
            return {"error": f"Image not found on GHCR"}
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def check_lscr_update(repository: str, tag: str, local_digest: Optional[str]) -> Optional[dict]:
    """
    Check LinuxServer.io Container Registry for updates.
    LSCR mirrors to GitHub Container Registry.
    """
    # lscr.io images are hosted on ghcr.io under linuxserver organization
    ghcr_repo = f"linuxserver/{repository.split('/')[-1]}"
    result = check_ghcr_update(ghcr_repo, tag, local_digest)
    if result:
        result["registry"] = "LinuxServer.io (LSCR)"
    return result


def check_image_update(image: str, local_digest: Optional[str]) -> dict:
    """Check if an image has an update available."""
    registry, repository, tag = parse_image_name(image)
    
    # Check if version is pinned (not :latest or untagged)
    is_pinned_version = tag not in ("latest", "") and not tag.startswith("v") == False
    # More specific: pinned if it looks like a semver (has numbers and dots)
    import re as re_module
    is_pinned_version = bool(re_module.match(r'^v?\d+[\.\d]*', tag)) if tag and tag != "latest" else False
    
    result = {
        "image": image,
        "registry": registry,
        "repository": repository,
        "tag": tag,
        "pinned_version": is_pinned_version,
        "checked_at": datetime.now().isoformat()
    }
    
    if registry in ("docker.io", "index.docker.io"):
        update_info = check_dockerhub_update(repository, tag, local_digest)
    elif registry == "ghcr.io":
        update_info = check_ghcr_update(repository, tag, local_digest)
    elif registry == "lscr.io":
        update_info = check_lscr_update(repository, tag, local_digest)
    else:
        # Unknown registry - can't check
        update_info = {"error": f"Unsupported registry: {registry}"}
    
    if update_info:
        result.update(update_info)
    
    # Add special message for pinned versions with updates
    if is_pinned_version and result.get("has_update"):
        result["pinned_update_note"] = f"Compose specifies version {tag} - update available but manually pinned"
    
    return result


def check_all_updates(force: bool = False) -> List[dict]:
    """
    Check all running containers from project folders for updates.
    Uses cache unless force=True or cache is older than 24 hours.
    """
    global _version_cache, _last_check_time
    
    with _check_lock:
        # Check if we can use cache
        if not force and _last_check_time:
            if datetime.now() - _last_check_time < _check_interval:
                return list(_version_cache.values())
        
        results = []
        
        # Get compose files from project folders
        compose_files = find_compose_files()
        
        # Get all images from compose files
        project_images = {}  # {project_name: {service: image}}
        for compose_file in compose_files:
            project_name = compose_file.parent.name
            images = parse_compose_images(compose_file)
            if images:
                project_images[project_name] = images
        
        # Get running containers
        running_containers = get_running_container_images()
        
        # Check each running container that matches a project
        for project_name, services in project_images.items():
            for service_name, image in services.items():
                # Find matching running container
                # Container names often follow pattern: project_service_1 or project-service-1
                matching_container = None
                local_digest = None
                local_created = None
                
                for container_name, container_info in running_containers.items():
                    # Check if this container uses the same image
                    if container_info["image"] == image or container_info["image"].split(':')[0] == image.split(':')[0]:
                        # Also verify it's from this project (loose match on name)
                        project_lower = project_name.lower().replace(' ', '').replace('-', '').replace('_', '')
                        container_lower = container_name.lower().replace('-', '').replace('_', '')
                        
                        if project_lower in container_lower or service_name.lower() in container_lower:
                            matching_container = container_name
                            local_digest = container_info.get("local_digest")
                            local_created = container_info.get("local_created")
                            break
                
                if matching_container:
                    # Check for updates
                    update_result = check_image_update(image, local_digest)
                    update_result["project"] = project_name
                    update_result["service"] = service_name
                    update_result["container"] = matching_container
                    update_result["local_created"] = local_created  # Add local image date
                    results.append(update_result)
        
        # Update cache
        _version_cache = {r.get("container", r.get("image")): r for r in results}
        _last_check_time = datetime.now()
        
        return results


def get_updates_with_notifications() -> Tuple[List[dict], List[dict]]:
    """
    Get update check results, separated into updates available and up-to-date.
    Returns (updates_available, up_to_date)
    """
    all_results = check_all_updates()
    
    updates_available = []
    up_to_date = []
    errors = []
    
    for result in all_results:
        if result.get("error"):
            errors.append(result)
        elif result.get("has_update"):
            updates_available.append(result)
        else:
            up_to_date.append(result)
    
    return updates_available, up_to_date, errors


def get_cached_results() -> List[dict]:
    """Get cached results without triggering a new check."""
    with _check_lock:
        return list(_version_cache.values())


def get_last_check_time() -> Optional[datetime]:
    """Get the time of the last version check."""
    return _last_check_time


def format_update_notification(result: dict) -> str:
    """Format an update result as a human-readable notification."""
    if result.get("error"):
        return f"⚠️ {result.get('project', 'Unknown')}/{result.get('service', 'Unknown')}: {result['error']}"
    elif result.get("has_update"):
        return f"🔄 {result.get('project', 'Unknown')}/{result.get('service', 'Unknown')}: Update available on {result.get('registry', 'registry')}"
    else:
        return f"✓ {result.get('project', 'Unknown')}/{result.get('service', 'Unknown')}: Up to date"


# For testing
if __name__ == "__main__":
    print("Docker Image Version Checker")
    print("=" * 50)
    print(f"Workspace: {get_workspace_root()}")
    print()
    
    print("Finding compose files...")
    compose_files = find_compose_files()
    for cf in compose_files:
        print(f"  📁 {cf.parent.name}/docker-compose.yml")
    print()
    
    print("Checking for updates (this may take a moment)...")
    print()
    
    updates, up_to_date, errors = get_updates_with_notifications()
    
    if updates:
        print("🔄 UPDATES AVAILABLE:")
        for u in updates:
            pinned_marker = " 📌" if u.get('pinned_version') else ""
            print(f"  • {u.get('project')}/{u.get('service')}: {u.get('image')}{pinned_marker}")
            if u.get('pinned_update_note'):
                print(f"    ⚠️  {u.get('pinned_update_note')}")
            print(f"    Local:  {u.get('local_digest', 'unknown')}")
            print(f"    Remote: {u.get('remote_digest', 'unknown')}")
            if u.get('last_updated'):
                print(f"    Updated: {u.get('last_updated')}")
        print()
    
    if up_to_date:
        print("✓ UP TO DATE:")
        for u in up_to_date:
            print(f"  • {u.get('project')}/{u.get('service')}: {u.get('image')}")
        print()
    
    if errors:
        print("⚠️ ERRORS:")
        for e in errors:
            print(f"  • {e.get('project')}/{e.get('service')}: {e.get('error')}")
        print()
    
    print(f"Last checked: {get_last_check_time()}")
