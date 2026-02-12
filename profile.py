"""
Universal StarRocks Profile v12 (Aggressive Multiplexing)
Features:
- Fixes "Mapping Failed" by forcing VLAN tagging on ALL links (LANs + Datasets)
- Allows 4 logical connections to share 2 physical ports
- IDE Node acts as NFS Server
"""

import geni.portal as portal
import geni.rspec.pg as pg
import geni.rspec.emulab as emulab

# Create a portal context.
pc = portal.Context()

# =============================================================
# 1. HARDWARE & NETWORK PARAMETERS
# =============================================================

pc.defineParameter(
    "nodeCount", "Number of Backend Nodes", portal.ParameterType.INTEGER, 3
)

pc.defineParameter(
    "phystype",
    "Hardware Type",
    portal.ParameterType.STRING,
    "d7525",
    [
        ("d7525", "Wisconsin d7525"),
        ("c6525-100g", "Utah c6525-100g"),
        ("c6525-25g", "Utah c6525-25g"),
        ("m510", "Utah m510"),
        ("xl170", "Utah xl170"),
        ("r6525", "Clemson r6526"),
    ],
)

pc.defineParameter(
    "linkCount",
    "Number of Network Links",
    portal.ParameterType.INTEGER,
    2,
    [(1, "1 Link"), (2, "2 Links")],
)

pc.defineParameter(
    "speedLan1",
    "Speed of Primary LAN (Gbps)",
    portal.ParameterType.INTEGER,
    100,
    [
        (200, "200 Gbps"),
        (100, "100 Gbps"),
        (56, "56 Gbps"),
        (40, "40 Gbps"),
        (25, "25 Gbps"),
        (10, "10 Gbps"),
    ],
)

pc.defineParameter(
    "speedLan2",
    "Speed of Secondary LAN (Gbps)",
    portal.ParameterType.INTEGER,
    25,
    [
        (200, "200 Gbps"),
        (100, "100 Gbps"),
        (56, "56 Gbps"),
        (40, "40 Gbps"),
        (25, "25 Gbps"),
        (10, "10 Gbps"),
    ],
)

# =============================================================
# 2. DATASET PARAMETERS
# =============================================================

pc.defineParameter(
    "datasetUrns",
    "Dataset URNs (Comma Separated)",
    portal.ParameterType.STRING,
    "urn:publicid:IDN+utah.cloudlab.us:fardatalab-pg0+stdataset+tpch-data, urn:publicid:IDN+utah.cloudlab.us:fardatalab-pg0+stdataset+starrocks-data",
    longDescription="Example: urn:1, urn:2",
)

pc.defineParameter(
    "datasetPaths",
    "Mount Paths (Comma Separated)",
    portal.ParameterType.STRING,
    "/nfs/tpch, /nfs/starrocks_data",
    longDescription="Example: /nfs/data1, /nfs/data2",
)

params = pc.bindParameters()
request = pc.makeRequestRSpec()

# =============================================================
# 3. PREPARE SCRIPTS
# =============================================================

urn_list = (
    [x.strip() for x in params.datasetUrns.split(",")] if params.datasetUrns else []
)
path_list = (
    [x.strip() for x in params.datasetPaths.split(",")] if params.datasetPaths else []
)

if len(urn_list) != len(path_list):
    perr = portal.ParameterError(
        "Number of URNs must match number of Paths", ["datasetUrns", "datasetPaths"]
    )
    pc.reportError(perr)

active_datasets = list(zip(urn_list, path_list))

path_args = ""
for i, (urn, mount) in enumerate(active_datasets):
    path_args += " " + mount

server_cmd = "sudo /bin/bash /local/repository/nfs-server.sh" + path_args
client_cmd = "sudo /bin/bash /local/repository/nfs-client.sh" + path_args

# =============================================================
# 4. NETWORK SETUP (AGGRESSIVE MULTIPLEXING)
# =============================================================

# --- LAN 1 (Primary) ---
lan1 = request.LAN("lan-primary")
lan1.bandwidth = params.speedLan1 * 1000000
# FORCE SHARING: This allows LAN1 to exist on the same wire as Dataset links
lan1.link_multiplexing = True
lan1.vlan_tagging = True
lan1.best_effort = True

# --- Hardware Check ---
single_port_hardware = ["d7525", "m510"]
actual_link_count = params.linkCount
if params.phystype in single_port_hardware and params.linkCount > 1:
    actual_link_count = 1

# --- LAN 2 (Secondary) ---
if actual_link_count == 2:
    lan2 = request.LAN("lan-secondary")
    lan2.bandwidth = params.speedLan2 * 1000000
    # FORCE SHARING: Also enable here to maximize mapper flexibility
    lan2.link_multiplexing = True
    lan2.vlan_tagging = True
    lan2.best_effort = True

# =============================================================
# 5. IDE NODE (NFS SERVER)
# =============================================================

ide = request.RawPC("ide")
ide.hardware_type = params.phystype
ide.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops:UBUNTU24-64-STD"

# --- IDE Interfaces (LANs) ---
ide_if1 = ide.addInterface("if1")
ide_if1.addAddress(
    pg.IPv4Address("10.{}.0.200".format(params.speedLan1), "255.255.255.0")
)
lan1.addInterface(ide_if1)

if actual_link_count == 2:
    ide_if2 = ide.addInterface("if2")
    ide_if2.addAddress(
        pg.IPv4Address("10.{}.0.200".format(params.speedLan2), "255.255.255.0")
    )
    lan2.addInterface(ide_if2)

# --- IDE Interfaces (Datasets) ---
for i, (urn, mount) in enumerate(active_datasets):
    # 1. Blockstore Node
    dsnode = request.RemoteBlockstore("dsnode-{}".format(i), mount)
    dsnode.dataset = urn

    # 2. Link Object
    dslink = request.Link("dslink-{}".format(i))

    # 3. CRITICAL: Enable Multiplexing BEFORE adding interfaces
    dslink.link_multiplexing = True
    dslink.vlan_tagging = True
    dslink.best_effort = True

    # 4. Connect Blockstore and IDE
    dslink.addInterface(dsnode.interface)

    # We add a new logical interface to the IDE node.
    # Because 'link_multiplexing=True', the mapper will stack this
    # onto the same physical port as 'if1' or 'if2'.
    dslink.addInterface(ide.addInterface())

# Start NFS Server
ide.addService(pg.Execute(shell="sh", command=server_cmd))

# =============================================================
# 6. CLIENT NODES
# =============================================================


def configure_client_node(name, ip_suffix):
    node = request.RawPC(name)
    node.hardware_type = params.phystype
    node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops:UBUNTU24-64-STD"

    # --- Interface 1 ---
    if1 = node.addInterface("if1")
    ip_str_1 = "10.{}.0.{}".format(params.speedLan1, ip_suffix)
    if1.addAddress(pg.IPv4Address(ip_str_1, "255.255.255.0"))
    lan1.addInterface(if1)

    # --- Interface 2 ---
    if actual_link_count == 2:
        if2 = node.addInterface("if2")
        ip_str_2 = "10.{}.0.{}".format(params.speedLan2, ip_suffix)
        if2.addAddress(pg.IPv4Address(ip_str_2, "255.255.255.0"))
        lan2.addInterface(if2)

    # Start NFS Client
    node.addService(pg.Execute(shell="sh", command=client_cmd))


# Instantiate
configure_client_node("fe", 100)
for i in range(params.nodeCount):
    configure_client_node("be-{}".format(i), i + 1)

pc.printRequestRSpec(request)
