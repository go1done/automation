import boto3
import hashlib
import json
import os
from datetime import datetime

logs = boto3.client("logs")
region = logs.meta.region_name
timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
backup_file = f"log_policies_backup_{region}_{timestamp}.json"


def backup_policies():
    """Back up all log resource policies to a timestamped file, with readable timestamps and prettified JSON."""
    response = logs.describe_resource_policies()
    raw_policies = response.get("resourcePolicies", [])
    clean_policies = []

    for policy in raw_policies:
        # Convert lastUpdatedTime (milliseconds) to readable timestamp
        ts_ms = policy.get("lastUpdatedTime")
        readable_time = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts_ms else None

        # Prettify policyDocument
        raw_doc = policy.get("policyDocument", "")
        try:
            doc_json = json.loads(raw_doc)
            pretty_doc = doc_json  # keep as dict for backup file
        except Exception:
            pretty_doc = raw_doc  # fallback to raw string if invalid

        clean_policies.append({
            "policyName": policy.get("policyName"),
            "lastUpdatedTime": readable_time,
            "policyDocument": pretty_doc
        })

    with open(backup_file, "w") as f:
        json.dump(clean_policies, f, indent=2)

    print(f"✅ Backup saved to: {backup_file}")
    return clean_policies


def hash_policy(policy_doc) -> str:
    """Create a SHA1 hash of the policy document (accepts dict or string)."""
    if isinstance(policy_doc, dict):
        doc_str = json.dumps(policy_doc, sort_keys=True)
    else:
        doc_str = policy_doc
    return hashlib.sha1(doc_str.encode("utf-8")).hexdigest()


def detect_duplicates(policies):
    """Detect policies with identical documents (by hash)."""
    hash_map = {}
    duplicates = []

    for policy in policies:
        name = policy["policyName"]
        doc = policy["policyDocument"]
        h = hash_policy(doc)

        if h in hash_map:
            duplicates.append((name, hash_map[h]["policyName"]))
        else:
            hash_map[h] = policy

    if duplicates:
        print("\n🔁 Duplicate policies detected (same document):")
        for dup, orig in duplicates:
            print(f"  - {dup} is a duplicate of {orig}")
    else:
        print("✅ No duplicate policies found.")

    return duplicates


def delete_policies(policy_names):
    """Delete specific log resource policies by name."""
    for name in policy_names:
        try:
            print(f"🗑️  Deleting policy: {name}")
            logs.delete_resource_policy(policyName=name)
            print(f"✅ Deleted: {name}")
        except logs.exceptions.ResourceNotFoundException:
            print(f"⚠️  Policy not found: {name}")
        except Exception as e:
            print(f"❌ Error deleting {name}: {e}")


def restore_policies_from_file(file_path):
    """Restore policies from a previously backed-up JSON file."""
    if not os.path.exists(file_path):
        print(f"❌ Backup file not found: {file_path}")
        return

    with open(file_path, "r") as f:
        policies = json.load(f)

    for policy in policies:
        name = policy.get("policyName")
        doc = policy.get("policyDocument")

        # Convert dict back to string for boto3
        if isinstance(doc, dict):
            doc_str = json.dumps(doc)
        else:
            doc_str = doc

        print(f"🔁 Restoring policy: {name}")
        try:
            logs.put_resource_policy(policyName=name, policyDocument=doc_str)
            print(f"✅ Restored: {name}")
        except Exception as e:
            print(f"❌ Error restoring {name}: {e}")


def menu():
    print("\n🛠️ CloudWatch Log Resource Policy Manager (region: {})".format(region))
    print("1️⃣  Backup existing policies")
    print("2️⃣  Detect duplicate policy documents")
    print("3️⃣  Delete policies by name (interactive)")
    print("4️⃣  Restore policies from backup file")
    print("5️⃣  Exit")
    return input("Choose an option: ").strip()


if __name__ == "__main__":
    saved_policies = []

    while True:
        choice = menu()

        if choice == "1":
            saved_policies = backup_policies()

        elif choice == "2":
            if not saved_policies:
                saved_policies = backup_policies()
            detect_duplicates(saved_policies)

        elif choice == "3":
            names = input("Enter policy names to delete (comma-separated): ").strip().split(",")
            names = [name.strip() for name in names if name.strip()]
            confirm = input(f"⚠️  Confirm delete of {len(names)} policies? (y/N): ").lower()
            if confirm == "y":
                delete_policies(names)
            else:
                print("❌ Deletion cancelled.")

        elif choice == "4":
            path = input("Enter path to backup JSON file: ").strip()
            restore_policies_from_file(path)

        elif choice == "5":
            print("👋 Exiting.")
            break

        else:
            print("❌ Invalid choice. Try again.")
