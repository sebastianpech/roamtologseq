import json
import re
import urllib
from posixpath import splitext
import os

import magic # Requires libmagic. Install separately eg. brew install libmagic on (macos)
import mimetypes

import dateutil.parser
from collections import OrderedDict

# -- Convert from roam attribute to logseq property
# Try to convert the following roam attributes to logseq properties
# Moving only works if the block has no block references and children.
# If it has, copy it instead of moving
convert_to_parent_data = [ 'source', 'α', 'inputfile', 'p', 'NEWTON_TOL_Δd', 'ft', 'coupling', 'MAX_R_INC', 'fiber_angle', 'CHECK_MAX_R_INC_AFTER', 'NEWTON_TOL_min_Δd', 'solver', 'use_primal_dual', 'NEWTON_TOL_Δu', 'relaxation', 'NEWTON_TOL_def', 'strict_convergence_of_subproblems', 'SUBPROBLEM_MAX_NR_ITR', 'β', 'model', 'linesearch', 'NEWTON_TOL_phase', 'NEWTON_TOL_min_Δu', 'Gc', 'ξ', 'material', 'N_phase', 'fix_failure_mode_threshold', 'target_deformation', 'c', 'easy_increment_threshold', 'increase_after', 'or', 'init_increment_size', 'TOL_MAX_PHASE_FIELD_EVOLUTION', 'min_Δt', 'newton_tol', 'Δt', 'max_iter', 'max_Δt', 'accept_solution_at_min_Δt', 'crack_orientation', 'max_iter_phase_field', 'step_function', 'use_converged_solution_for_NL', 'use_peak_finding_alorithm', 'start_from_file', 'break_on_maximum_iterations', 'max_iter_deformation_field', 'κ', 'Δft_scale', 'ΔGc', 'disable_contact_constraint', 'consider_mode_III', 'consider_mode_I', 'consider_mode_II', 'peak_finder_tol', 'N_steps_peak_finder']
copy_if_cant_be_moved = True

# -- Download an relink files stored in roam
# Tag to add to a block in case it could not be converted to a logseq property
# due to block references on this block or children.
tag_not_converted = "#notconverted"
# Output folder for downloaded assets
assets_folder = '/Users/spech/SynologyDrive/Projekte/roam_to_logseq/assets'

# -- Task management related conversion
# Add first date reference in a scheduled block as scheduled property
scheduled_tag = '[[📅]]'
# Convert roam tags to task managent markers in logseq. Like #waiting to WAITING
# The order here is important as only the first occurring replacement is made.
# 'overwrite_DONE' is used to ignore blocks that are already done.
# Like #waiting on a done block should not be converted to WAITING
convert_task_management = OrderedDict()
convert_task_management['canceled'] = {'attribute': 'CANCELED', 'overwrite_DONE': True}
convert_task_management['Warte']    = {'attribute': 'WAITING', 'overwrite_DONE': False}

# Path to roam json file to convert
roam_database = '/Users/spech/SynologyDrive/Projekte/roam_to_logseq/TestSebastian 3.json'
# Path cleaned up database should be exported to
output_database ='output.json'

re_block_ref_candindate = r"\(\(([0-9A-z-_]+?)\)\)"
re_firebase_filename = r"(?P<prefix>!?)\[(?P<name>.*?)\]\((?P<link>https://firebasestorage[^\)]*(?<=%2F)(?P<file>.*?)(?=\?).*?)\)"
re_firebase_pdf = r"{{\[*pdf\]*: (?P<link>https://firebasestorage[^}]*(?<=%2F)(?P<file>.*?)(?=\?).*?)}"
re_firebase_link_only = r"(?P<link>https://firebasestorage[^\?]*(?<=%2F)(?P<file>.*?)(?=\?).*?)(\s|$)"
re_attributes = r'^([^\n`]*?)::(.*)'
re_DNP_ref = r'.*?\[\[(?P<date>(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}(st|nd|rd|th), \d{4})\]\]'

def load_roam_db(json_file):
    with open(json_file) as f:
        data = json.load(f)
        return data

# Structure of roam json (List of pages)
# Page
# - title
# - children (list of blocks)
#
# Block
# - string
# - uid

def map_children(data, parent, f):
    """Run f recursively on all child block in data"""
    if 'string' in data:
        f(data, parent)
    if 'children' in data:
        for child in data['children'].copy():
            map_children(child, data, f)

def flatten_block_ids(child, parent):
    """Extract all block by id and store in global dict block_by_id"""
    block_by_id[child['uid']] = child

def extract_block_references(child, parent):
    """Extract all blocks referencing a block and store in global dict block_references"""
    refs = re.findall(re_block_ref_candindate, child['string'])
    for ref in refs:
        if not ref in block_references: block_references[ref] = set()
        block_references[ref].add(child['uid'])

def get_attributes(child, parent):
    """
    Extract all roam attributes and the text containing them.

    This function is mainly for setting up convert_to_parent_data and checking for
    special characters in the attribute definitions.
    """
    m = re.match(re_attributes, child['string'])
    if m is not None:
        attribute, attribute_text = m.groups()
        if attribute not in all_attributes: all_attributes[attribute] = []
        all_attributes[attribute].append(child['string'])

def rename_attributes(child, parent):
    """ rename all roam attributes either to [[attribute]]: or try to add them logseq block properties """
    m = re.match(re_attributes, child['string'])
    if m is not None:
        attribute, attribute_text = m.groups()
        if not ('[[' in attribute or '((' in attribute):
            if (attribute in convert_to_parent_data) and 'string' in parent:
                if 'children' not in child and (child['uid'] not in block_references or len(block_references[child['uid']]) == 0):
                    parent['string'] += "\n{}::{}".format(attribute, attribute_text)
                    parent['children'].remove(child)
                else:
                    if copy_if_cant_be_moved:
                        parent['string'] += "\n{}::{}".format(attribute, attribute_text)
                    child['string'] = '[[{}]]:{}'.format(attribute, attribute_text)
            else:
                child['string'] = '[[{}]]:{}'.format(attribute, attribute_text)

def generate_new_string_from_matches(inps, match):
    """ Convert found markdown links into a format matching logseq and download linked files to assets folder """
    out_string = ""
    for (i,m) in enumerate(match):
        if i == 0:
            out_string += inps[0:m.span()[0]]
        else:
            out_string += inps[match[i-1].span()[1]+1:m.span()[0]]
        g = m.groupdict()
        # pdf imported in logseq as ![name](path), same as images
        # other files without !
        name = g.get('name', '')
        link = g.get('link')
        file = g.get('file')
        prefix = g.get('prefix','')
        # Download files
        target_path = os.path.join(assets_folder, file)
        if not os.path.isfile(target_path):
            # Check if the file was renamed before
            trial_filenames = [f for f in os.listdir(assets_folder) if f.startswith(file)]
            if len(trial_filenames) == 1:
                file = trial_filenames[0]
            else:
                print("Downloading {}".format(link))
                urllib.request.urlretrieve(link, target_path)
        _, extension = splitext(file)
        if extension.lower() == ".pdf":
            prefix = '!'
        elif extension == '':
            extension = mimetypes.guess_extension(magic.from_file(target_path,  mime=True))
            os.rename(target_path, target_path+extension)
            file += extension
        out_string += "{}[{}](../assets/{})".format(prefix, name, file)
    out_string += inps[match[-1].span()[1]+1:]
    return out_string

def download_firebase_files(child, parent):
    """ download files stored in roam and link them to match logseq definitions """
    if 'firebasestorage.googleapis.com' in child['string']:
        match = list(re.finditer(re_firebase_filename, child['string']))
        if len(match) == 0:
            # Maybe pdf
            match = list(re.finditer(re_firebase_pdf, child['string']))
        if len(match) == 0:
            # Maybe just a link
            match = list(re.finditer(re_firebase_link_only, child['string']))
        if len(match) == 0:
            # Add tag that this couldn't be converted
            child['string'] += " {}".format(tag_not_converted)
        else:
            child['string'] = generate_new_string_from_matches(child['string'], match)

def roam_date_to_logseq_scheduled(roam_date_string):
    """ turn a roam DNP reference into a SCHEDULED block property """
    date = dateutil.parser.parse(roam_date_string)
    scheduled_date = "SCHEDULED: <{dt:%Y}-{dt:%m}-{dt:%d} {dt:%a}>".format(dt=date)
    return scheduled_date

def add_scheduled_information(child, parent):
    """ add a SCHEDULED property to every block which contains a DNP reference and a certain scheduled tag (scheduled_tag) """
    if scheduled_tag in child['string']:
        m = re.match(re_DNP_ref, child['string'])
        if m is not None:
            date = m.groupdict()['date']
            child['string'] += "\n{}".format(roam_date_to_logseq_scheduled(date))

def find_pagename_format(pagename, text):
    """
    search for possible variations of page and tag reference styles for a pagename and retrun the found string and location.
    The location also includes an additional space (if found).
    """
    for format in ['#{}'.format(pagename), '#[[{}]]'.format(pagename), '[[{}]]'.format(pagename)]:
        location = text.find(format)
        if location == -1:
            continue
        additional_space = 0
        if len(text) > location+len(format) and text[location+len(format)] == ' ':
            additional_space = 1
        return format, (location, location+len(format)+additional_space)
    return None, (0,0)

def get_roam_todo_done(text):
    """
    Return TODO or DONE for a block if it is properly formatted.
    Also return the location including an extra space (if found)
    """
    if '{{[[TODO]]}}' in text or '{{[[DONE]]}}' in text:
        number_of_opening_p = 0
        for s in text:
            if s == '{':
                number_of_opening_p += 1
            else:
                break
        keyword = text[number_of_opening_p+2:number_of_opening_p+6]
        len_of_keyword = 2+4+2
        # Check if {} are correctly balancing
        for i in range(0, number_of_opening_p):
            if text[number_of_opening_p+len_of_keyword+i] != '}':
                return None, (0,0)
        additional_space = 0
        if len(text) > 2*number_of_opening_p+len_of_keyword and text[2*number_of_opening_p+len_of_keyword] == ' ':
            additional_space += 1
        return keyword, (0, 2*number_of_opening_p+len_of_keyword+additional_space)
    return None, (0,0)

def convert_task_managent_tags(child, parent):
    """ Convert special tags which habe a meaning in the logseq task management system eq. a todo block with #canceled is turned into CANCELED """
    keyword, keyword_slice = get_roam_todo_done(child['string'])
    if keyword is not None:
        for pagename in convert_task_management:
            found, found_slice = find_pagename_format(pagename, child['string'])
            if found is None: continue
            if keyword == 'DONE' and convert_task_management[pagename]['overwrite_DONE'] == False: return
            child['string'] = '{attribute} {text_before}{text_after}'.format(attribute=convert_task_management[pagename]['attribute'], text_before=child['string'][keyword_slice[1]:found_slice[0]], text_after=child['string'][found_slice[1]:]).strip()
            return

def find_queries(text):
    "Return all slices of text containing a query"
    found_query = []
    i = 0
    while i < len(text):
        next_query_at = text.find('query', i)
        if next_query_at == -1: return []
        # Find query open
        if text[next_query_at-2:next_query_at] == '{{':
            open_len = 2
        elif text[next_query_at-4:next_query_at] == '{{[[':
            open_len = 4
        else:
            i = next_query_at+1
            continue
        open_at = next_query_at-open_len
        # Find query close
        balancing_closing = 2
        balanced_at = 0
        for j in range(next_query_at+1, len(text)):
            if text[j] == '{': balancing_closing += 1
            if text[j] == '}': balancing_closing -= 1
            if balancing_closing == 0:
                balanced_at = j+1
                break
        found_query.append((open_at, balanced_at))
        i = balanced_at
    return found_query

def wrap_queries_as_code(child, parent):
    query_slices = find_queries(child['string'])
    if len(query_slices) > 0:
        out_string = ''
        for (i,slice) in enumerate(query_slices):
            if i == 0:
                out_string += child['string'][0:slice[0]]
            else:
                out_string += child['string'][query_slices[i-1][1]:slice[0]]
            out_string += '`{}`'.format(child['string'][slice[0]:slice[1]])
        out_string += child['string'][query_slices[-1][1]:]
        child['string'] = out_string

data = load_roam_db(roam_database)

all_attributes = {}
for page in data:
    map_children(page, {}, get_attributes)

block_by_id = {}
for page in data:
    map_children(page, {}, flatten_block_ids)

block_references = {}
for page in data:
    map_children(page, {}, extract_block_references)

for page in data:
    map_children(page, {}, wrap_queries_as_code)

for page in data:
    map_children(page, {}, download_firebase_files)

for page in data:
    map_children(page, {}, rename_attributes)

for page in data:
    map_children(page, {}, add_scheduled_information)

for page in data:
    map_children(page, {}, convert_task_managent_tags)

with open(output_database, 'w') as outfile:
    json.dump(data, outfile)