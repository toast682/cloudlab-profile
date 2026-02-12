#!/bin/bash
#
# Setup NFS server for multiple exports.
#
# This script is called by profile.py with a list of directories to export
# as arguments (e.g., ./nfs-server.sh /nfs/tpch /nfs/starrocks)
#

# Source Emulab paths
if [ -f /etc/emulab/paths.sh ]; then
    . /etc/emulab/paths.sh
fi

# The name of the NFS network (Must match profile.py)
NFSNETNAME="nfsLan"

# Ensure we have arguments
if [ $# -eq 0 ]; then
    echo "No NFS directories provided to export. Exiting."
    exit 0
fi

# 1. Update /etc/hosts to ensure we can resolve the NFS LAN IP
if ! (grep -q $HOSTNAME-$NFSNETNAME /etc/hosts); then
    echo "WARNING: $HOSTNAME-$NFSNETNAME is not in /etc/hosts"
fi

# 2. Install NFS Server (Ubuntu/Debian)
apt-get update
if ! dpkg -s nfs-kernel-server >/dev/null 2>&1; then
    echo "Installing NFS Server..."
    apt-get --assume-yes install nfs-kernel-server nfs-common
    service nfs-kernel-server stop
fi

# 3. Calculate the Subnet
# We grab the IP of this node on the NFS LAN and assume a /24 subnet.
NFSIP=`grep -i $HOSTNAME-$NFSNETNAME /etc/hosts | awk '{print $1}'`
# Extract first 3 octets: 10.10.10.5 -> 10.10.10.0
NFSNET=`echo $NFSIP | awk -F. '{printf "%s.%s.%s.0", $1, $2, $3}'`

echo "NFS IP: $NFSIP"
echo "NFS Subnet: $NFSNET/24"

# 4. Configure /etc/exports
# Loop through ALL arguments passed to the script ($@)
for EXPORT_DIR in "$@"
do
    echo "Processing export: $EXPORT_DIR"

    # Create the directory if it doesn't exist
    # (CloudLab usually mounts the blockstore here, but we ensure it exists)
    if [ ! -d "$EXPORT_DIR" ]; then
        mkdir -p -m 755 "$EXPORT_DIR"
        chown nobody:nogroup "$EXPORT_DIR"
    fi

    # Check if already exported to avoid duplicates
    if ! grep -q "^$EXPORT_DIR" /etc/exports; then
        echo "Exporting $EXPORT_DIR to $NFSNET/24"
        # rw = read/write, no_root_squash = allow root on client to be root on server
        echo "$EXPORT_DIR $NFSNET/24(rw,sync,no_root_squash,no_subtree_check,fsid=0)" >> /etc/exports
    else
        echo "$EXPORT_DIR is already in /etc/exports"
    fi
done

# 5. Configure RPC Bind (Security / Binding)
echo "OPTIONS=\"-l -h 127.0.0.1 -h $NFSIP\"" > /etc/default/rpcbind
sed -i.bak -e "s/^rpcbind/#rpcbind/" /etc/hosts.deny

# 6. Restart Services
echo "Restarting RPC and NFS services..."
service rpcbind stop
sleep 1
service rpcbind start
service nfs-kernel-server start

# Export explicitly to be safe
exportfs -a

echo "NFS Server Setup Complete."