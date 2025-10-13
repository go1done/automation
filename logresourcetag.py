#!/usr/bin/env python3
import argparse
import boto3
import json
from collections import defaultdict
import sys

logs_client = boto3.client("logs")

def list_resource_policies():
    """
    Returns a list of policy dicts, each including name and policy document.
    """
    policies = []
    paginator = logs_client.get_paginator("describe_resource_policies")
    for page in paginator.paginate():
        for p in page.get("resourcePolicies", []):
            # p includes fields like: policyName, policyDocument (JSON string), etc.
            policies.append(p)
    return policies

def parse_policy_document(policy_document_str):
    """
    policy_document_str is a JSON string or dict; returns dict.
    """
    if isinstance(policy_document_str, dict):
        return policy_document_str
    try:
        return json.loads(policy_document_str)
    except Exception as e:
        print(f"ERROR: cannot parse policy document: {e}", file=sys.stderr)
        return {}

def get_log_group_tags(log_group_name):
    """
    Returns a dict of tags for the given log group name.
    If not found or error, returns empty dict.
    """
    try:
        resp = logs_client.list_tags_log_group(logGroupName=log_group_name)
        return resp.get("tags", {}) or {}
    except logs_client.exceptions.ResourceNotFoundException:
        # log group doesn’t exist
        return {}
    except Exception as e:
        print(f"Warning: failed to get tags for {log_group_name}: {e}", file=sys.stderr)
        return {}

def extract_log_groups_from_statement(stmt):
    """
    Given one statement dict from a policy, return a list of log group names referenced.
    E.g. resources like "arn:aws:logs:...:log-group:/aws/lambda/xyz:*"
    Returns list of log group name strings.
    """
    log_groups = []
    resources = stmt.get("Resource")
    if resources is None:
        return log_groups
    if not isinstance(resources, (list, tuple)):
        resources = [resources]
    for res in resources:
        if not isinstance(res, str):
            continue
        # We expect something like "arn:aws:logs:<region>:<acct>:log-group:<loggroupname>:*"
        marker = ":log-group:"
        if marker in res:
            parts = res.split(marker, 1)
            after = parts[1]
            # after might be e.g. "/aws/lambda/foo:*" or "/aws/lambda/foo"
            # strip wildcard suffix
            # If it has “:*” at end, remove that
            if after.endswith(":*"):
                after = after[:-2]
            elif after.endswith("*"):
                after = after[:-1]
            # Also strip any trailing colon
            if after.endswith(":"):
                after = after[:-1]
            log_groups.append(after)
    return log_groups

def extract_policy_to_tags(policy_name, policy_dict):
    """
    Given policy name and parsed policy dict, return a set of "key=value" tag strings
    collected across all log groups referenced in the policy.
    """
    tags_set = set()
    for stmt in policy_dict.get("Statement", []):
        lg_names = extract_log_groups_from_statement(stmt)
        for lg in lg_names:
            tagdict = get_log_group_tags(lg)
            for k, v in tagdict.items():
                tags_set.add(f"{k}={v}")
    return tags_set

def build_policy_tag_mapping():
    """
    Returns a mapping: policy_name -> set of tag strings.
    Also returns auxiliary info: how many log groups, what log groups.
    """
    mapping = {}
    aux = {}  # policy_name -> dict with details
    policies = list_resource_policies()
    for p in policies:
        name = p.get("policyName")
        doc_str = p.get("policyDocument")
        parsed = parse_policy_document(doc_str)
        tags = extract_policy_to_tags(name, parsed)
        mapping[name] = tags

        # optional extra: track which log groups were seen
        lg_set = set()
        for stmt in parsed.get("Statement", []):
            lg_set.update(extract_log_groups_from_statement(stmt))
        aux[name] = {
            "log_groups": lg_set,
            "num_log_groups": len(lg_set),
        }
    return mapping, aux

def print_table(mapping, aux=None, sort_by="name"):
    """
    Print a table: policy name | #tags | tags | #log_groups | log group names
    """
    # Prepare rows
    rows = []
    for name, tagset in mapping.items():
        tags = sorted(tagset)
        tag_str = ", ".join(tags) if tags else "(none)"
        row = {
            "policy_name": name,
            "num_tags": len(tags),
            "tags": tag_str,
        }
        if aux and name in aux:
            row["num_log_groups"] = aux[name].get("num_log_groups", 0)
            row["log_groups"] = aux[name].get("log_groups", set())
        else:
            row["num_log_groups"] = ""
            row["log_groups"] = set()
        rows.append(row)

    # Sorting
    if sort_by == "name":
        rows.sort(key=lambda r: r["policy_name"])
    elif sort_by == "num_tags":
        rows.sort(key=lambda r: r["num_tags"], reverse=True)

    # Determine column widths
    w1 = max(len("PolicyName"), max((len(r["policy_name"]) for r in rows), default=0))
    w2 = max(len("#Tags"), max((len(str(r["num_tags"])) for r in rows), default=0))
    w3 = max(len("Tags"), max((len(r["tags"]) for r in rows), default=0))
    w4 = max(len("#LGs"), max((len(str(r["num_log_groups"])) for r in rows), default=0))
    # for log group list, we may not print full set inline

    header = (f"{'PolicyName'.ljust(w1)}  {'#Tags'.rjust(w2)}  "
              f"{'Tags'.ljust(w3)}  {'#LGs'.rjust(w4)}  LogGroups")
    print(header)
    print("-" * len(header))
    for r in rows:
        lg_list = ",".join(sorted(r["log_groups"])) if r["log_groups"] else ""
        print(f"{r['policy_name'].ljust(w1)}  "
              f"{str(r['num_tags']).rjust(w2)}  "
              f"{r['tags'].ljust(w3)}  "
              f"{str(r['num_log_groups']).rjust(w4)}  "
              f"{lg_list}")

def main():
    parser = argparse.ArgumentParser(
        description="List CloudWatch Logs resource policies and their associated log group tags"
    )
    parser.add_argument(
        "--sort", choices=["name", "num_tags"], default="name",
        help="Sort output by policy name or by number of tags"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output mapping in JSON form instead of table"
    )

    args = parser.parse_args()

    mapping, aux = build_policy_tag_mapping()

    if args.json:
        # build a JSON-serializable dict
        out = {}
        for name, tags in mapping.items():
            out[name] = {
                "tags": sorted(tags),
                "num_tags": len(tags),
                "log_groups": sorted(list(aux.get(name, {}).get("log_groups", []))),
            }
        print(json.dumps(out, indent=2))
    else:
        print_table(mapping, aux, sort_by=args.sort)


if __name__ == "__main__":
    main()
