#!/bin/sh
set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

for bucket_name in "$OBJECT_STORAGE_BUCKET" "$TEST_OBJECT_STORAGE_BUCKET"; do
  mc mb --ignore-existing "local/$bucket_name"
  mc anonymous set none "local/$bucket_name"
  mc ilm rule remove --all --force "local/$bucket_name" >/dev/null 2>&1 || true
  mc ilm rule add --expire-days 1 --prefix staging/ "local/$bucket_name" >/dev/null
done

policy_name="privexa-object-access"
policy_file="/tmp/$policy_name.json"
cat >"$policy_file" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::$OBJECT_STORAGE_BUCKET/*",
        "arn:aws:s3:::$TEST_OBJECT_STORAGE_BUCKET/*"
      ]
    }
  ]
}
EOF

mc admin user remove local "$OBJECT_STORAGE_ACCESS_KEY" >/dev/null 2>&1 || true
mc admin policy remove local "$policy_name" >/dev/null 2>&1 || true
mc admin policy create local "$policy_name" "$policy_file"
mc admin user add local "$OBJECT_STORAGE_ACCESS_KEY" "$OBJECT_STORAGE_SECRET_KEY"
mc admin policy attach local "$policy_name" --user "$OBJECT_STORAGE_ACCESS_KEY"
