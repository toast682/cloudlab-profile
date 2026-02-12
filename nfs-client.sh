#!/bin/bash
#
# Setup NFS client and mount multiple directories.
#
# This script is called by profile.py with a list of directories to mount
# as arguments (e.g., ./nfs-client.sh /nfs/tpch /nfs/starrocks)
#

# Source Emulab paths
if [ -f /etc/emulab/paths.sh ]; then
    . /etc/emulab/paths.sh
fi

# The name of the NFS network (Must match profile.py)
NFSSERVER="ide-lan-primary"

# Ensure we have arguments
if [ $# -eq 0 ]; then
    echo "No NFS directories provided to mount. Exiting."
    exit 0
fi

# 1. Install NFS Client (Ubuntu/Debian)
apt-get update
if ! dpkg -s nfs-common >/dev/null 2>&1; then
    echo "Installing NFS Common..."
    apt-get --assume-yes install nfs-common
fi

# 2. Wait for NFS Server to be reachable
echo "Waiting for NFS server ($NFSSERVER) to be reachable..."
while ! ping -c 1 -W 1 $NFSSERVER > /dev/null; do
    echo "Waiting for ping response from $NFSSERVER..."
    sleep 2
done

# 3. Wait for NFS RPC service
while ! (rpcinfo -s $NFSSERVER | grep -q nfs); do
    echo "Waiting for RPC/NFS on $NFSSERVER ..."
    sleep 2
done

# 4. Mount Loop
# Standard mount options for performance/reliability
MNTOPTS="rw,bg,sync,hard,intr"

# Loop through ALL arguments passed to the script ($@)
for MOUNT_DIR in "$@"
do
    echo "Processing mount: $MOUNT_DIR"

    # Create the local mount point
    if [ ! -d "$MOUNT_DIR" ]; then
        echo "Creating local mount point: $MOUNT_DIR"
        mkdir -p -m 755 "$MOUNT_DIR"
    fi

    # Check if already mounted
    if grep -qs "$MOUNT_DIR" /proc/mounts; then
        echo "$MOUNT_DIR is already mounted."
    else
        echo "Mounting $NFSSERVER:$MOUNT_DIR to $MOUNT_DIR ..."
        
        # Try to mount
        if ! mount -t nfs -o $MNTOPTS $NFSSERVER:$MOUNT_DIR $MOUNT_DIR; then
            echo "WARNING: First mount attempt failed. Retrying in 5 seconds..."
            sleep 5
            if ! mount -t nfs -o $MNTOPTS $NFSSERVER:$MOUNT_DIR $MOUNT_DIR; then
                echo "FATAL: Could not mount $MOUNT_DIR"
                # We do not exit here, so we can try mounting the other directories
            fi
        else
            echo "Successfully mounted $MOUNT_DIR"
        fi
    fi
done

echo "NFS Client Setup Complete."