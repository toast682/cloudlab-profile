"""
Universal StarRocks Profile v9 (IDE as NFS Server)
Features:
- CSV Input for Datasets (URNs and Paths)
- IDE Node acts as NFS Server
- All other nodes mount NFS from IDE
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
        ("d7525", "Wisconsin d7525 (Single Link Limit)"),
        ("c6525-100g", "Utah c6525-100g (Dual Link Capable)"),
        ("c6525-25g", "Utah c6525-25g (Dual Link Capable)"),
        ("m510", "Utah m510 (Single Link Limit)"),
        ("xl170", "Utah xl170 (Dual Link Capable)"),
        ("r6525", "Clemson r6526 (Dual Link Capable)"),
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
# 3. PARSE CSV INPUTS
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

# Generate Argument Strings for Scripts
path_args = ""
for i, (urn, mount) in enumerate(active_datasets):
    path_args += " " + mount

server_cmd = "sudo /bin/bash /local/repository/nfs-server.sh" + path_args
client_cmd = "sudo /bin/bash /local/repository/nfs-client.sh" + path_args

# =============================================================
# 4. NETWORK SETUP
# =============================================================

lan1 = request.LAN("lan-primary")
lan1.bandwidth = params.speedLan1 * 1000000

single_port_hardware = ["d7525", "m510"]
actual_link_count = params.linkCount
if params.phystype in single_port_hardware and params.linkCount > 1:
    actual_link_count = 1

if actual_link_count == 2:
    lan2 = request.LAN("lan-secondary")
    lan2.bandwidth = params.speedLan2 * 1000000

# =============================================================
# 5. IDE NODE (NFS SERVER) CONFIGURATION
# =============================================================

ide = request.RawPC("ide")
ide.hardware_type = params.phystype
ide.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops:UBUNTU24-64-STD"

# -- IDE Networking --
# Primary Interface (Server IP will be 10.{speed}.0.200)
ide_if1 = ide.addInterface("if1")
ide_if1.addAddress(
    pg.IPv4Address("10.{}.0.200".format(params.speedLan1), "255.255.255.0")
)
lan1.addInterface(ide_if1)

# Secondary Interface (Optional)
if actual_link_count == 2:
    ide_if2 = ide.addInterface("if2")
    ide_if2.addAddress(
        pg.IPv4Address("10.{}.0.200".format(params.speedLan2), "255.255.255.0")
    )
    lan2.addInterface(ide_if2)

# -- Attach Datasets to IDE --
for i, (urn, mount) in enumerate(active_datasets):
    dsnode = request.RemoteBlockstore("dsnode-{}".format(i), mount)
    dsnode.dataset = urn

    # Dedicated link for the blockstore to the IDE node
    dslink = request.Link("dslink-{}".format(i))
    dslink.addInterface(dsnode.interface)
    dslink.addInterface(ide.addInterface())
    dslink.best_effort = True
    dslink.vlan_tagging = True
    dslink.link_multiplexing = True

# -- Run NFS Server Script on IDE --
ide.addService(pg.Execute(shell="bash", command=server_cmd))

# =============================================================
# 6. CLIENT NODES (FE & BACKENDS)
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

    # --- Interface 2 (Conditional) ---
    if actual_link_count == 2:
        if2 = node.addInterface("if2")
        ip_str_2 = "10.{}.0.{}".format(params.speedLan2, ip_suffix)
        if2.addAddress(pg.IPv4Address(ip_str_2, "255.255.255.0"))
        lan2.addInterface(if2)

    # --- Run NFS Client Script ---
    node.addService(pg.Execute(shell="bash", command=client_cmd))


# Instantiate Frontend (ID = 100)
configure_client_node("fe", 100)

# Instantiate Backend Nodes (ID = 1, 2, 3...)
for i in range(params.nodeCount):
    configure_client_node("be-{}".format(i), i + 1)

pc.printRequestRSpec(request)
