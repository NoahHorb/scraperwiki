#!/usr/bin/env python3
"""
OSRS Wiki NPC Database Scraper
Extracts NPC combat data from Infobox Monster templates via MediaWiki API
"""

import requests
import json
import re
import time
from typing import Dict, List, Optional, Any
from collections import defaultdict

# Configuration
WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"
USER_AGENT = "PvMPerformanceTracker/1.0 (NPC Database Scraper; Noah.Horbinski@gmail.com)"
RATE_LIMIT_DELAY = 0.5  # Seconds between requests (be respectful!)

class OSRSWikiScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})
        self.npcs = {}

    def get_all_npc_pages(self) -> List[str]:
        """
        Get all pages in the 'Monsters' category
        """
        print("Fetching list of all NPC pages...")

        pages = []
        continue_token = None

        while True:
            params = {
                'action': 'query',
                'list': 'categorymembers',
                'cmtitle': 'Category:Monsters',
                'cmlimit': 500,  # Max allowed
                'format': 'json'
            }

            if continue_token:
                params['cmcontinue'] = continue_token

            response = self.session.get(WIKI_API_URL, params=params)
            data = response.json()

            if 'query' in data and 'categorymembers' in data['query']:
                for page in data['query']['categorymembers']:
                    pages.append(page['title'])

            # Check if there are more results
            if 'continue' in data:
                continue_token = data['continue']['cmcontinue']
                time.sleep(RATE_LIMIT_DELAY)
            else:
                break

        print(f"Found {len(pages)} NPC pages")
        return pages

    def get_page_content(self, page_title: str) -> Optional[str]:
        """
        Get the raw wiki text for a specific page
        """
        params = {
            'action': 'query',
            'prop': 'revisions',
            'rvprop': 'content',
            'titles': page_title,
            'format': 'json',
            'formatversion': 2
        }

        response = self.session.get(WIKI_API_URL, params=params)
        data = response.json()

        if 'query' in data and 'pages' in data['query']:
            page = data['query']['pages'][0]
            if 'revisions' in page and len(page['revisions']) > 0:
                return page['revisions'][0]['content']

        return None

    def find_matching_brace(self, text: str, start_pos: int) -> int:
        """
        Find the matching closing braces for an opening {{
        Returns the position of the matching }}
        """
        depth = 0
        i = start_pos

        while i < len(text) - 1:
            if text[i:i+2] == '{{':
                depth += 1
                i += 2
            elif text[i:i+2] == '}}':
                depth -= 1
                if depth == 0:
                    return i
                i += 2
            else:
                i += 1

        return -1

    def parse_infobox_monster(self, wiki_text: str) -> List[Dict[str, Any]]:
        """
        Parse all Infobox Monster templates from wiki text
        Returns a list since some pages have multiple versions (Entry/Normal/Hard, phases, etc.)

        Handles three scenarios:
        1. Multi Infobox with multiple {{Infobox Monster}} templates (e.g., Doom with phases)
        2. Standalone {{Infobox Monster}} with multiple versions (e.g., Zulrah)
        3. Multiple standalone {{Infobox Monster}} templates (e.g., bosses with separate forms)
        """
        infoboxes = []

        print(f"  [DEBUG] Wiki text length: {len(wiki_text)} characters")
        print(f"  [DEBUG] First 500 chars: {wiki_text[:500]}")

        # First, try to find Multi Infobox structure
        multi_infobox_pattern = r'\{\{Multi Infobox'
        multi_match = re.search(multi_infobox_pattern, wiki_text, re.IGNORECASE)

        if multi_match:
            print(f"  [DEBUG] Found Multi Infobox at position {multi_match.start()}")

            # Find the matching closing braces
            start_pos = multi_match.start()
            end_pos = self.find_matching_brace(wiki_text, start_pos)

            if end_pos != -1:
                multi_content = wiki_text[multi_match.end():end_pos]
                print(f"  [DEBUG] Multi Infobox content length: {len(multi_content)}")
                print(f"  [DEBUG] First 300 chars of multi content: {multi_content[:300]}")

                # Find all text/item pairs
                text_pattern = re.compile(r'\|text\d*\s*=\s*([^\n]+)')
                item_pattern = re.compile(r'\|item\d*\s*=')

                text_matches = list(text_pattern.finditer(multi_content))
                item_matches = list(item_pattern.finditer(multi_content))

                print(f"  [DEBUG] Found {len(text_matches)} text labels and {len(item_matches)} items")

                # For each item marker, find the corresponding Infobox Monster
                for i, item_match in enumerate(item_matches):
                    item_start = item_match.end()

                    # Find corresponding text label (should be before this item)
                    text_label = None
                    for text_match in reversed(text_matches):
                        if text_match.start() < item_match.start():
                            text_label = text_match.group(1).strip()
                            break

                    print(f"  [DEBUG] Item {i} has label: {text_label}")

                    # Find the next item or text marker (to know where this infobox ends)
                    next_marker_pos = len(multi_content)
                    if i + 1 < len(item_matches):
                        next_marker_pos = item_matches[i + 1].start()
                    elif i < len(text_matches) - 1:
                        # Check if there's a text marker after this
                        for text_match in text_matches:
                            if text_match.start() > item_match.start():
                                next_marker_pos = text_match.start()
                                break

                    # Extract content between this item and the next marker
                    section = multi_content[item_start:next_marker_pos]
                    print(f"  [DEBUG] Section length: {len(section)}, first 200 chars: {section[:200]}")

                    # Find {{Infobox Monster...}} in this section
                    infobox_pattern = r'\{\{Infobox Monster'
                    infobox_match = re.search(infobox_pattern, section, re.IGNORECASE)

                    if infobox_match:
                        print(f"  [DEBUG] Found Infobox Monster in item {i}")

                        # Find matching closing braces for this infobox
                        infobox_start = infobox_match.start()
                        infobox_end = self.find_matching_brace(section, infobox_start)

                        if infobox_end != -1:
                            infobox_content = section[infobox_match.end():infobox_end]
                            print(f"  [DEBUG] Infobox content length: {len(infobox_content)}")

                            infobox_data = self.parse_infobox_content(infobox_content, phase_label=text_label)
                            if infobox_data:
                                infoboxes.append(infobox_data)
                                print(f"  [DEBUG] Successfully parsed infobox {i}")
                        else:
                            print(f"  [DEBUG] Could not find closing braces for infobox {i}")
                    else:
                        print(f"  [DEBUG] No Infobox Monster found in item {i}")
            else:
                print(f"  [DEBUG] Could not find closing braces for Multi Infobox")

        # Also check for standalone Infobox Monster (not in Multi Infobox)
        if not multi_match:
            print(f"  [DEBUG] No Multi Infobox found, looking for standalone Infobox Monster")

            standalone_pattern = r'\{\{Infobox Monster'

            pos = 0
            while True:
                match = re.search(standalone_pattern, wiki_text[pos:], re.IGNORECASE)
                if not match:
                    break

                # Calculate absolute positions
                match_start_absolute = pos + match.start()  # Where {{ starts in full text
                match_end_absolute = pos + match.end()      # Where pattern ends in full text

                print(f"  [DEBUG] Found standalone Infobox Monster at position {match_start_absolute}")

                # Find matching closing braces (using absolute position)
                end_pos = self.find_matching_brace(wiki_text, match_start_absolute)

                if end_pos != -1:
                    # Extract content from end of pattern to closing brace
                    infobox_content = wiki_text[match_end_absolute:end_pos]
                    print(f"  [DEBUG] Standalone infobox content length: {len(infobox_content)}")
                    print(f"  [DEBUG] First 200 chars: {repr(infobox_content[:200])}")

                    infobox_data = self.parse_infobox_content(infobox_content)
                    if infobox_data:
                        infoboxes.append(infobox_data)
                        print(f"  [DEBUG] Successfully parsed standalone infobox")

                    pos = end_pos + 2
                else:
                    print(f"  [DEBUG] Could not find closing braces for standalone infobox")
                    break

        print(f"  [DEBUG] Total infoboxes parsed: {len(infoboxes)}")
        return infoboxes

    def parse_infobox_content(self, infobox_content: str, phase_label: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Parse the content of a single Infobox Monster
        Handles multiple versions (version1, version2, etc.) within the same infobox
        Returns dict with version info included
        """
        data = {'versions': [], 'phaseLabel': phase_label}

        # Parse key-value pairs
        raw_data = {}
        lines = infobox_content.split('\n')
        print(f"    [DEBUG] Total lines to parse: {len(lines)}")
        print(f"    [DEBUG] First 5 lines: {lines[:5]}")

        for line in lines:
            line = line.strip()
            if line.startswith('|'):
                line = line[1:].strip()
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    raw_data[key] = value

                    # Debug: print version-related keys as we find them
                    if 'version' in key or 'max hit' in key:
                        print(f"    [DEBUG] Found key: '{key}' = '{value[:50]}...'")

        print(f"    [DEBUG] Parsed {len(raw_data)} key-value pairs from infobox")

        # Show some sample keys
        sample_keys = list(raw_data.keys())[:15]
        print(f"    [DEBUG] First 15 keys: {sample_keys}")

        # Check specifically for version keys
        version_keys = [k for k in raw_data.keys() if k.startswith('version')]
        print(f"    [DEBUG] Version-related keys found: {version_keys}")

        # Check if this infobox has multiple versions by looking for version1, version2, etc.
        has_versions = any(k.startswith('version') and len(k) > 7 and k[7:].isdigit() for k in raw_data.keys())
        print(f"    [DEBUG] Has versions: {has_versions}")

        if has_versions:
            # Find how many versions there are by looking for version1, version2, etc.
            version_numbers = set()
            for key in raw_data.keys():
                if key.startswith('version') and len(key) > 7 and key[7:].isdigit():
                    version_num = int(key[7:])
                    version_numbers.add(version_num)

            print(f"    [DEBUG] Version numbers found: {sorted(version_numbers)}")

            # Extract data for each version
            for version_num in sorted(version_numbers):
                version_data = {}
                version_data['versionNumber'] = version_num
                version_data['versionName'] = raw_data.get(f'version{version_num}', f'Version {version_num}')
                version_data['bucketName'] = raw_data.get(f'bucketname{version_num}', version_data['versionName'])

                # Extract version-specific fields
                for key, value in raw_data.items():
                    # Skip the version name keys themselves
                    if key == f'version{version_num}' or key == f'bucketname{version_num}':
                        continue

                    # Check if this key ends with the version number
                    if key.endswith(str(version_num)):
                        # Remove the version number suffix
                        base_key = key[:-len(str(version_num))]
                        cleaned_value = self.clean_wiki_text(value)
                        version_data[base_key] = cleaned_value
                        print(f"    [DEBUG] Version {version_num}: '{key}' -> '{base_key}' = '{cleaned_value[:30]}...'")
                    # Check if this is a shared field (no version number suffix)
                    elif not any(key.endswith(str(v)) for v in version_numbers):
                        # This is a shared field (no version number)
                        cleaned_value = self.clean_wiki_text(value)
                        version_data[key] = cleaned_value

                print(f"    [DEBUG] Version {version_num} ('{version_data['versionName']}') has {len(version_data)} fields")

                # Debug: show attack style and max hit for this version
                if 'attack style' in version_data:
                    print(f"    [DEBUG] Version {version_num} attack style: '{version_data['attack style']}'")
                if 'max hit' in version_data:
                    print(f"    [DEBUG] Version {version_num} max hit: '{version_data['max hit']}'")

                data['versions'].append(version_data)
        else:
            # Single version, use all data as-is
            version_data = {}
            for key, value in raw_data.items():
                cleaned_value = self.clean_wiki_text(value)
                version_data[key] = cleaned_value
            version_data['versionNumber'] = 1
            version_data['versionName'] = version_data.get('name', 'Default')
            print(f"    [DEBUG] Single version with {len(version_data)} fields")
            data['versions'].append(version_data)

        return data if data['versions'] else None


    def clean_wiki_text(self, text: str) -> str:
        """
        Remove wiki markup from text
        """
        # Remove references like <ref>...</ref>
        text = re.sub(r'<ref[^>]*>.*?</ref>', '', text, flags=re.DOTALL)

        # Remove HTML comments
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

        # Remove wiki links [[link|text]] -> text (but keep the link text for max hit parsing)
        # DON'T remove the [[ ]] from max hit values yet - we need them for parsing
        # text = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', text)

        # Remove wiki formatting
        # text = re.sub(r"'{2,}", '', text)  # Bold/italic

        # Remove templates like {{template}} - but be careful not to remove content
        # text = re.sub(r'\{\{[^}]*\}\}', '', text)

        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def parse_number(self, value: str) -> Optional[int]:
        """
        Parse a number from wiki text, handling ranges and special cases
        """
        if not value:
            return None

        # Remove commas
        value = value.replace(',', '')

        # Handle ranges (take the max)
        if '–' in value or '-' in value:
            parts = re.split(r'[–-]', value)
            try:
                return int(parts[-1].strip())
            except ValueError:
                return None

        # Try to extract first number
        match = re.search(r'\d+', value)
        if match:
            try:
                return int(match.group())
            except ValueError:
                return None

        return None

    def parse_max_hit(self, infobox_data: Dict[str, str]) -> Dict[str, int]:
        """
        Parse max hit data from infobox
        Handles different attack styles with different max hits
        """
        max_hits = {}

        # Get attack styles for this NPC
        attack_style = infobox_data.get('attack style', '').lower()
        has_attack_style = bool(attack_style.strip())

        print(f"    [DEBUG] Attack style for max hit parsing: '{attack_style}'")

        # Check for different max hit fields
        fields_to_check = [
            ('max hit', None),
            ('maxhit', None),
            ('max melee', 'melee'),
            ('max magic', 'magic'),
            ('max ranged', 'ranged'),
            ('max mage', 'magic'),
            ('max range', 'ranged'),
        ]

        for field_name, attack_type in fields_to_check:
            if field_name in infobox_data:
                value = infobox_data[field_name]

                print(f"    [DEBUG] Found field '{field_name}' = '{value[:100]}...'")

                # Check if this contains <br/> or <br> - indicates multiple max hits
                if '<br' in value.lower():
                    # [Same as before - br handling code]
                    parts = re.split(r'<br\s*/?>',  value, flags=re.IGNORECASE)
                    base_max_hit = None

                    for part in parts:
                        part = part.strip()
                        if not part:
                            continue

                        match = re.search(r'(\d+)\s*(?:\(([^)]+)\))?', part)
                        if match:
                            hit_value = int(match.group(1))
                            attack_name = match.group(2)

                            if attack_name:
                                attack_name = attack_name.strip().lower()
                                attack_name = re.sub(r'\[\[|\]\]', '', attack_name)
                                if 'melee' in attack_name:
                                    attack_name = 'melee'
                                elif 'magic' in attack_name or 'mage' in attack_name:
                                    attack_name = 'magic'
                                elif 'ranged' in attack_name or 'range' in attack_name:
                                    attack_name = 'ranged'
                                elif '/' in attack_name:
                                    attack_name = attack_name.split('/')[0].strip().replace(' ', '_')
                                else:
                                    attack_name = attack_name.replace(' ', '_')
                                max_hits[attack_name] = hit_value
                            else:
                                base_max_hit = hit_value

                    if base_max_hit is not None:
                        if has_attack_style and 'typeless' not in attack_style:
                            if 'melee' in attack_style or 'slash' in attack_style or 'crush' in attack_style or 'stab' in attack_style:
                                max_hits.setdefault('melee', base_max_hit)
                            if 'magic' in attack_style or 'mage' in attack_style:
                                max_hits.setdefault('magic', base_max_hit)
                            if 'ranged' in attack_style or 'range' in attack_style:
                                max_hits.setdefault('ranged', base_max_hit)
                        else:
                            max_hits.setdefault('typeless', base_max_hit)

                # Check if this is a complex format with multiple attacks separated by commas
                elif '[[' in value or '),' in value:
                    # [Same complex parsing as before]
                    parts = value.split(',')
                    for part in parts:
                        part = part.strip()
                        match = re.search(r'(\d+)\s*(?:\(\[\[([^\]]+)\]\]\)|\(([^)]+)\))', part)
                        if match:
                            hit_value = int(match.group(1))
                            attack_name = match.group(2) or match.group(3)
                            attack_name = attack_name.strip().lower()
                            attack_name = re.sub(r'\[\[|\]\]', '', attack_name)
                            if 'melee' in attack_name:
                                attack_name = 'melee'
                            elif 'magic' in attack_name or 'mage' in attack_name:
                                attack_name = 'magic'
                            elif 'ranged' in attack_name or 'range' in attack_name:
                                attack_name = 'ranged'
                            elif '/' in attack_name:
                                attack_name = attack_name.split('/')[0].strip().replace(' ', '_')
                            else:
                                attack_name = attack_name.replace(' ', '_')
                            max_hits[attack_name] = hit_value
                        else:
                            num_match = re.search(r'(\d+)', part)
                            if num_match and not max_hits:
                                hit_value = int(num_match.group(1))
                                if has_attack_style and 'typeless' not in attack_style:
                                    if 'melee' in attack_style or 'slash' in attack_style or 'crush' in attack_style or 'stab' in attack_style:
                                        max_hits.setdefault('melee', hit_value)
                                    if 'magic' in attack_style or 'mage' in attack_style:
                                        max_hits.setdefault('magic', hit_value)
                                    if 'ranged' in attack_style or 'range' in attack_style:
                                        max_hits.setdefault('ranged', hit_value)
                                else:
                                    max_hits['typeless'] = hit_value
                else:
                    # Simple format, just a number
                    hit_value = self.parse_number(value)
                    if hit_value is not None:
                        if has_attack_style and 'typeless' not in attack_style:
                            # Apply to all attack styles from attack_style field
                            if 'melee' in attack_style or 'slash' in attack_style or 'crush' in attack_style or 'stab' in attack_style:
                                max_hits['melee'] = hit_value
                            if 'magic' in attack_style or 'mage' in attack_style:
                                max_hits['magic'] = hit_value
                            if 'ranged' in attack_style or 'range' in attack_style:
                                max_hits['ranged'] = hit_value

                            if attack_type:
                                max_hits[attack_type] = hit_value
                        else:
                            # Typeless or no attack style - use typeless or default
                            if 'typeless' in attack_style:
                                max_hits['typeless'] = hit_value
                            else:
                                max_hits['default'] = hit_value

        # Final cleanup
        if 'default' in max_hits and has_attack_style and 'typeless' not in attack_style and len(max_hits) > 1:
            default_val = max_hits['default']
            del max_hits['default']

            if 'melee' in attack_style or 'slash' in attack_style or 'crush' in attack_style or 'stab' in attack_style:
                max_hits.setdefault('melee', default_val)
            if 'magic' in attack_style or 'mage' in attack_style:
                max_hits.setdefault('magic', default_val)
            if 'ranged' in attack_style or 'range' in attack_style:
                max_hits.setdefault('ranged', default_val)

        print(f"    [DEBUG] Final max_hits (after default cleanup): {max_hits}")
        return max_hits

    def parse_attributes(self, infobox_data: Dict[str, str]) -> List[str]:
        """
        Parse monster attributes from infobox
        Common attributes: demon, dragon, undead, fiery, etc.
        """
        attributes = []

        # Check various attribute fields
        attribute_fields = ['attributes', 'attribute', 'cat']

        for field in attribute_fields:
            if field in infobox_data:
                value = infobox_data[field].lower()

                # Split on commas and clean
                parts = [part.strip() for part in value.split(',')]
                attributes.extend([p for p in parts if p])

        # Also check for specific known attributes
        known_attributes = [
            'demon', 'dragon', 'undead', 'fiery', 'leafy', 'vampyre',
            'kalphite', 'shade', 'xerician', 'golem', 'tzhaar'
        ]

        for attr in known_attributes:
            if attr in infobox_data:
                if infobox_data[attr].lower() in ['yes', 'true', '1']:
                    if attr not in attributes:
                        attributes.append(attr)

        return attributes

    def parse_immunities(self, infobox_data: Dict[str, str]) -> Dict[str, bool]:
        """
        Parse immunity information
        """
        immunities = {
            'poison': False,
            'venom': False,
            'cannon': False,
            'thrall': False
        }

        # Check various immunity field names
        immunity_mappings = {
            'immunepoison': 'poison',
            'immunevenom': 'venom',
            'immunecannon': 'cannon',
            'immunethrall': 'thrall',
            'poison immune': 'poison',
            'venom immune': 'venom',
            'cannon immune': 'cannon',
            'thrall immune': 'thrall',
        }

        for field, immunity_type in immunity_mappings.items():
            if field in infobox_data:
                value = infobox_data[field].lower()
                if value in ['yes', 'true', '1', 'immune']:
                    immunities[immunity_type] = True

        return immunities

    def parse_venom_type(self, infobox_data: Dict[str, str]) -> Optional[str]:
        """
        Parse venom type (if the monster is venomous)
        Returns: None, 'venom', 'poison', or specific type
        """
        # Check if monster is poisonous
        poison_field = infobox_data.get('poisonous', '').lower()
        if poison_field in ['yes', 'true', '1']:
            # Check if it's venom specifically
            venom_field = infobox_data.get('venom', '').lower()
            if venom_field in ['yes', 'true', '1']:
                return 'venom'
            return 'poison'

        # Check venom field directly
        venom_field = infobox_data.get('venom', '').lower()
        if venom_field in ['yes', 'true', '1']:
            return 'venom'

        return None

    def extract_npc_data(self, page_title: str, wiki_text: str) -> List[Dict[str, Any]]:
        """
        Extract structured NPC data from wiki page
        Returns a list of NPCs since one page can have multiple versions/phases
        """
        infoboxes = self.parse_infobox_monster(wiki_text)

        print(f"\n{'='*60}")
        print(f"DEBUG: {page_title}")
        print(f"{'='*60}")
        print(f"Found {len(infoboxes)} infoboxes")

        if not infoboxes:
            return []

        all_npcs = []

        for infobox_idx, infobox in enumerate(infoboxes):
            phase_label = infobox.get('phaseLabel')  # e.g., "Normal", "Shielded", "Burrowed"

            print(f"\nInfobox {infobox_idx}:")
            print(f"  Phase Label: {phase_label}")
            print(f"  Versions: {len(infobox.get('versions', []))}")

            # Each infobox may have multiple versions
            for version_idx, version_data in enumerate(infobox.get('versions', [])):
                print(f"\n  Version {version_idx}:")
                print(f"    Version Number: {version_data.get('versionNumber')}")
                print(f"    Version Name: {version_data.get('versionName')}")
                print(f"    Has 'max hit' key: {'max hit' in version_data}")
                print(f"    Has 'attack style' key: {'attack style' in version_data}")

                if 'max hit' in version_data:
                    print(f"    Max hit raw value: {version_data['max hit'][:150]}...")
                if 'attack style' in version_data:
                    print(f"    Attack style: {version_data['attack style']}")

                # Parse max hits for different attack styles
                max_hits = self.parse_max_hit(version_data)

                print(f"    Parsed max_hits: {max_hits}")

                if not max_hits:
                    # Skip versions with no max hit data
                    print(f"    ✗ Skipping - no max hits parsed")
                    continue

                # Create min hits (all default to 0, users can curate later)
                min_hits = {style: 0 for style in max_hits.keys()}

                # Parse additional properties
                attributes = self.parse_attributes(version_data)
                immunities = self.parse_immunities(version_data)
                venom_type = self.parse_venom_type(version_data)

                # Create a unique identifier for this version
                version_name = version_data.get('versionName', '')
                bucket_name = version_data.get('bucketName', version_name)

                # Construct full name with phase label if present
                base_name = version_data.get('name', page_title)

                # Build full name: base_name + (phase_label) + (bucket_name)
                name_parts = [base_name]

                # Add phase label if it exists and isn't already in the base name
                if phase_label and phase_label.lower() not in base_name.lower():
                    name_parts.append(f"({phase_label})")

                # Add bucket name if it's different from version name and not already included
                if bucket_name and bucket_name != base_name and (not phase_label or bucket_name.lower() != phase_label.lower()):
                    # Check if bucket_name is already in the constructed name
                    constructed_so_far = ' '.join(name_parts)
                    if bucket_name.lower() not in constructed_so_far.lower():
                        name_parts.append(f"- {bucket_name}")

                full_name = ' '.join(name_parts)

                # Extract NPC IDs (can be comma-separated)
                npc_id = version_data.get('id', '')

                # Extract other useful data
                npc_data = {
                    'name': full_name,
                    'baseName': base_name,
                    'phase': phase_label,
                    'version': bucket_name,
                    'id': npc_id,
                    'combatLevel': self.parse_number(version_data.get('combat', '')),
                    'hitpoints': self.parse_number(version_data.get('hitpoints', '')),
                    'size': self.parse_number(version_data.get('size', '')),
                    'maxHit': max_hits,
                    'minHit': min_hits,
                    'attackSpeed': self.parse_number(version_data.get('attack speed', '')),
                    'attackStyle': version_data.get('attack style', ''),
                    'aggressive': version_data.get('aggressive', '').lower() == 'yes',

                    # Poison/Venom properties
                    'poisonous': version_data.get('poisonous', '').lower() == 'yes',
                    'venomType': venom_type,

                    # Attributes (demon, dragon, undead, etc.)
                    'attributes': attributes,

                    # Immunities
                    'immunities': immunities,

                    # Combat stats
                    'attackLevel': self.parse_number(version_data.get('att', '')),
                    'strengthLevel': self.parse_number(version_data.get('str', '')),
                    'defenceLevel': self.parse_number(version_data.get('def', '')),
                    'magicLevel': self.parse_number(version_data.get('mage', '')),
                    'rangedLevel': self.parse_number(version_data.get('range', '')),

                    # Defensive bonuses
                    'stabDefence': self.parse_number(version_data.get('dstab', '')),
                    'slashDefence': self.parse_number(version_data.get('dslash', '')),
                    'crushDefence': self.parse_number(version_data.get('dcrush', '')),
                    'magicDefence': self.parse_number(version_data.get('dmagic', '')),
                    'rangedDefence': self.parse_number(version_data.get('drange', '')),

                    # Offensive bonuses
                    'attackBonus': self.parse_number(version_data.get('astab', '')),
                    'strengthBonus': self.parse_number(version_data.get('astr', '')),
                    'rangedAttackBonus': self.parse_number(version_data.get('arange', '')),
                    'magicAttackBonus': self.parse_number(version_data.get('amagic', '')),

                    # Slayer info
                    'slayerLevel': self.parse_number(version_data.get('slaylvl', '')),
                    'slayerXp': self.parse_number(version_data.get('slayxp', '')),

                    # Metadata
                    'wikiPage': page_title,
                    'examine': version_data.get('examine', ''),
                }

                # Only include non-null values (but keep empty lists/dicts)
                cleaned_data = {}
                for k, v in npc_data.items():
                    if v is not None and v != '':
                        cleaned_data[k] = v
                    elif isinstance(v, (list, dict)) and len(v) > 0:
                        cleaned_data[k] = v

                all_npcs.append(cleaned_data)
                print(f"    ✓ Created NPC: {full_name}")

        return all_npcs

    def scrape_all_npcs(self, limit: Optional[int] = None, test_pages: Optional[List[str]] = None):
        """
        Scrape all NPC pages and extract data
        """
        if test_pages:
            pages = test_pages
            print(f"Testing with specific pages: {test_pages}")
        else:
            pages = self.get_all_npc_pages()
            if limit:
                pages = pages[:limit]

        total = len(pages)

        for i, page_title in enumerate(pages, 1):
            print(f"\n{'='*60}")
            print(f"Processing {i}/{total}: {page_title}")
            print(f"{'='*60}")

            try:
                wiki_text = self.get_page_content(page_title)

                if wiki_text:
                    npc_list = self.extract_npc_data(page_title, wiki_text)

                    if npc_list:
                        for npc_data in npc_list:
                            if npc_data.get('maxHit'):
                                # Use NPC ID(s) as key, or generate unique key
                                npc_ids = npc_data.get('id', '')
                                npc_name = npc_data.get('name', page_title)
                                version = npc_data.get('version', '')
                                phase = npc_data.get('phase', '')

                                # Create a unique key with version info
                                if npc_ids:
                                    # Use first ID as primary key
                                    primary_id = npc_ids.split(',')[0].strip()
                                    if version or phase:
                                        unique_key = f"{primary_id}_{version}_{phase}".replace(' ', '_').replace('-', '_')
                                    else:
                                        unique_key = f"{primary_id}"
                                else:
                                    # Fallback to name-based key
                                    unique_key = npc_name.replace(' ', '_').replace('(', '').replace(')', '').replace('-', '_')

                                self.npcs[unique_key] = npc_data
                                print(f"  ✓ Extracted: {npc_name} (Max hits: {npc_data['maxHit']})")
                    else:
                        print(f"  ✗ No NPC data found")
                else:
                    print(f"  ✗ Could not fetch page content")

            except Exception as e:
                print(f"  ✗ Error: {e}")
                import traceback
                traceback.print_exc()

            # Rate limiting
            time.sleep(RATE_LIMIT_DELAY)

    def save_database(self, filename: str = 'npc_database.json'):
        """
        Save the scraped data to JSON file
        """
        output = {
            '_metadata': {
                'source': 'OSRS Wiki MediaWiki API',
                'scraper': 'PvM Performance Tracker NPC Scraper',
                'total_npcs': len(self.npcs),
                'format': 'NPC ID/Name -> NPC Data',
                'note': 'minHit values default to 0 and should be curated manually for special attacks'
            },
            'npcs': self.npcs
        }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n✓ Saved {len(self.npcs)} NPCs to {filename}")

    def print_summary(self):
        """
        Print summary statistics
        """
        print("\n" + "="*60)
        print("SCRAPING SUMMARY")
        print("="*60)
        print(f"Total NPCs extracted: {len(self.npcs)}")

        # Count attack styles
        attack_styles = defaultdict(int)
        for npc in self.npcs.values():
            for style in npc.get('maxHit', {}).keys():
                attack_styles[style] += 1

        print("\nAttack Style Distribution:")
        for style, count in sorted(attack_styles.items()):
            print(f"  {style}: {count} NPCs")

        # List all NPCs
        print("\nAll extracted NPCs:")
        for i, (npc_id, npc_data) in enumerate(self.npcs.items()):
            print(f"  {npc_data.get('name', npc_id)}: {npc_data.get('maxHit', {})}")

        print("="*60)


def main():
    """
    Main execution
    """
    print("="*60)
    print("OSRS Wiki NPC Database Scraper - TEST MODE")
    print("="*60)
    print(f"API URL: {WIKI_API_URL}")
    print(f"User-Agent: {USER_AGENT}")
    print(f"Rate Limit: {RATE_LIMIT_DELAY}s between requests")
    print("="*60)
    print()

    scraper = OSRSWikiScraper()

    # Test with just Vorkath and Doom of Mokhaiotl
    test_pages = ['Zulrah','Vorkath']
    scraper.scrape_all_npcs()

    # Print summary
    scraper.print_summary()

    # Save to file
    scraper.save_database('npc_database.json')

    print("\nDone! Check the debug output above to see what's happening.")


if __name__ == '__main__':
    main()