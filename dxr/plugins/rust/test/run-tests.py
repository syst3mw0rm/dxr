# Run a series of tests specified by a manifest file. 
# Note: this is hackey and horribly insecure (see the FIXME in one_test). We should
# improve things.
# Manifest format: any number of lines following
#
# 'build_command' 'expected_output.csv'*
#
# Whitespace and anything following '#' is ignored.
# Runs build_command and compares the expected output with the actual output,
# doing a logical compare.
#
# Command line format:
# run-tests.py manifest_file [--verbose] [--allow-rows] [--allow-cols] [--dont-tidy-up]

# TODO would be awesome if we didn't care about conrete ids, just graph consistency

import sys, os, shutil, subprocess, csv

allow_extra_rows = False
allow_extra_cols = False
verbose = False
dont_tidy_up = False

def main():
    global allow_extra_rows
    global allow_extra_cols
    global verbose
    global dont_tidy_up

    manifest = None
    for i in range(1, len(sys.argv)):
        arg = sys.argv[i]
        if arg.startswith('--'):
            if arg == '--verbose':
                verbose = True
            elif arg == '--allow-rows':
                allow_extra_rows = True
            elif arg == '--allow-cols':
                allow_extra_cols = True
            elif arg == '--dont-tidy-up':
                dont_tidy_up = True
            else:
                print "Unknown argument", arg
                return
        else:
            if manifest:
                print "Warning: argument ingnored -", arg
            else:
                manifest = arg

    if not manifest:
        print "Manifest file not specified in arguments"
        return

    try:
        manifest = open(manifest, 'r')
        process_manifest(manifest)
        manifest.close()
    finally:
        pass

def process_manifest(manifest):
    aborted = 0
    failed = 0
    passed = 0

    for l in manifest:
        parsed = parse_line(l)
        if parsed:
            result = one_test(parsed)
            if result == None:
                aborted += 1
            elif result == False:
                failed += 1
                print "Test failed:", parsed
            elif result == True:
                passed += 1
            # If we don't tidy up after ourselves, we can't do more than one test
            if dont_tidy_up:
                break

    print "Passed %d, failed %d, errors: %d (total: %d)"%(passed, failed, aborted, passed + failed + aborted)

# Take a line consisting of a build command and >0 csv file names and return that
# as a tuple: (build_command, [expected_files]) or None
def parse_line(line):
    line = line.strip()
    if line[0] == '#':
        return
    if '#' in line:
        base = line[0:line.find('#')]
    else:
        base = line

    cur = ""
    quoted = False
    args = []
    for c in base:
        if c == "'":
            if quoted:
                args.append(cur)
                cur = ""
            quoted = not quoted
        elif quoted:
            cur += c

    if quoted:
        print "Found unclosed quote in line \"%s\""%line
        return None

    if not args:
        return None

    if len(args) < 2:
        print "Requires at least a build command and one expected file in line \"%s\""%line
        return None

    return (args[0], args[1:])
    
TEMP_DIR = 'tmp'

def one_test((build_command, expected)):
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)

    try:
        if verbose:
            print "running '%s'..."%os.path.join(os.getcwd(), build_command)
        # FIXME!!!! Totally insecure, anything in manifest gets executed.
        stdout = open('tmp/stdout.log', 'w')
        stderr = open('tmp/stderr.log', 'w')
        ret_code = subprocess.call(
            "DXR_RUST_TEMP_FOLDER=%s "%os.path.join(os.getcwd(), TEMP_DIR) + os.path.join(os.getcwd(), build_command),
            stdout=stdout, stderr=stderr, shell=True)

        if ret_code > 0:
            print "build command '%s' failed with code '%d'"%(build_command,ret_code)
            return None

        success = True
        for ex in expected:
            success &= compare_output(ex, os.path.join(TEMP_DIR, ex))

        return success

    finally:
        if not dont_tidy_up:
            shutil.rmtree(TEMP_DIR)


def compare_output(expected, found):
    expect_file = open(expected)
    found_file = open(found)
    if verbose:
        print "comparing '%s' and '%s'"%(expected,found)

    expected_lines = parse_csv(expect_file)
    found_lines = parse_csv(found_file)
    found_map = make_map(found_lines)

    success = True

    for ex in expected_lines:
        if (ex[0],ex[1]['extent_start']) in found_map:
            result = found_map.pop((ex[0],ex[1]['extent_start']))
            # compare columns
            for col in ex[1].keys():
                if col not in result[1]:
                    success = False
                    if verbose:
                        print "FAIL: missing column '%s' in row:"%col, ex
                elif ex[1][col] != result[1][col]:       
                    success = False
                    if verbose:
                        print "FAIL: found '%s', expected '%s' on row:"%(result[1][col],ex[1][col]), result

            # check for extra columns
            if not allow_extra_cols:
                for col in result[1]:
                    if col not in ex[1]:
                        success = False
                        if verbose:
                            print "FAIL: found extra column '%s' in row:"%col, result
        else:
            success = False
            if verbose:
                print "FAIL: missing row:", ex

    if not allow_extra_rows:
        # check for remaining elements in found_map
        if found_map:
            success = False
        if verbose:
            for val in found_map.values():
                print "FAIL: found extra row:", val

    return success


# Parse a csv file into a list of lines consisting of kind and an args map.
def parse_csv(input):
    result = []
    parsed_iter = csv.reader(input)
    for line in parsed_iter:
        kind = line[0]
        args = {}
        for i in range(1, len(line), 2):
            args[line[i]] = line[i + 1]
        # Ignore lines without these details, which we will use for looking up
        # lines.
        if 'extent_start' in args:
            result.append((kind, args))
        elif verbose:
            print "skipping '%s'"%line

    return result


#TODO I'm sure there is a nice, pythonic way to do this
def make_map(lines):
    map = {}
    for l in lines:
        map[(l[0],l[1]['extent_start'])] = l
    return map


if __name__ == '__main__':
    main()

