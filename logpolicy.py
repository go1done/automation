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
    """Back up all log resource policies to a timestamped file."""
    response = logs.describe_resource_policies()
    policies = response.get("resourcePolicies", [])

    with open(backup_file, "w") as f:
        json.dump(policies, f, indent=2)

    print(f"✅ Backup saved to: {backup_file}")
    return policies


def hash_policy(policy_doc: str) -> str:
    """Create a SHA1 hash of the policy document."""
    return hashlib.sha1(policy_doc.encode("utf-8")).hexdigest()


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
        print("🔁 Duplicate policies detected (same document):")
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
    """Restore policies from a previously backed up JSON file."""
    if not os.path.exists(file_path):
        print(f"❌ Backup file not found: {file_path}")
        return

    with open(file_path, "r") as f:
        policies = json.load(f)

    for policy in policies:
        name = policy["policyName"]
        doc = policy["policyDocument"]
        print(f"🔁 Restoring policy: {name}")
        try:
            logs.put_resource_policy(policyName=name, policyDocument=doc)
            print(f"✅ Restored: {name}")
        except Exception as e:
            print(f"❌ Error restoring {name}: {e}")


def menu():
    print("\n🛠️ CloudWatch Log Resource Policy Manager (region: {})".format(region))
    print("1️⃣  Backup existing policies")
    print("2️⃣  Detect duplicates")
    print("3️⃣  Delete policies by name (interactive)")
    print("4️⃣  Restore policies from backup")
    print("5️⃣  Exit")

    choice = input("Choose an option: ").strip()
    return choice


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
