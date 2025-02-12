import os
import socket
import sys
import time

from collections import Counter
import ray
import pyphi
import numpy as np

num_cpus = int(sys.argv[1])
subsystem_size = int(sys.argv[2])

ray.init(address=os.environ["ip_head"])

print("Nodes in the Ray cluster:")
print(ray.nodes())


# 5-node
rand_5_lc = np.array([[0.34689379, 0.2957891 , 0.        , 0.        , 0.        ],
                      [0.38024179, 0.62936339, 0.23397856, 0.        , 0.        ],
                      [0.        , 0.89299704, 0.56666642, 0.767733  , 0.        ],
                      [0.        , 0.        , 0.7380186 , 0.00871498, 0.57483179],
                      [0.        , 0.        , 0.        , 0.34261003, 0.03579365]])
network_5 = pyphi.network_generator.build_network(pyphi.network_generator.UNIT_FUNCTIONS["ising"], rand_5_lc)
subsystem_5 = pyphi.Subsystem(network_5,(0,0,0,0,0))

# 6-node
rand_6_lc = np.array([[0.32272698, 0.0966845 , 0.        , 0.        , 0.        , 0.        ],  
                      [0.25359363, 0.66248673, 0.32064434, 0.        , 0.        , 0.        ],  
                      [0.        , 0.22052159, 0.60659632, 0.68563877, 0.        , 0.        ],  
                      [0.        , 0.        , 0.44492414, 0.04713127, 0.57081638, 0.        ],  
                      [0.        , 0.        , 0.        , 0.64174987, 0.77189138, 0.01277639],
                      [0.        , 0.        , 0.        , 0.        , 0.56703909, 0.31629065]])

network_6 = pyphi.network_generator.build_network(pyphi.network_generator.UNIT_FUNCTIONS["ising"], rand_6_lc)
subsystem_6 = pyphi.Subsystem(network_6,(0,0,0,0,0,0))

# 7-node
rand_7_lc = np.array([[0.32272698, 0.0966845 , 0.        , 0.        , 0.        , 0.        , 0.        ],  
                      [0.25359363, 0.66248673, 0.32064434, 0.        , 0.        , 0.        , 0.        ],  
                      [0.        , 0.22052159, 0.60659632, 0.68563877, 0.        , 0.        , 0.        ],  
                      [0.        , 0.        , 0.44492414, 0.04713127, 0.57081638, 0.        , 0.        ],  
                      [0.        , 0.        , 0.        , 0.64174987, 0.77189138, 0.01277639, 0.        ],  
                      [0.        , 0.        , 0.        , 0.        , 0.56703909, 0.31629065, 0.86103476],
                      [0.        , 0.        , 0.        , 0.        , 0.        , 0.8087123 , 0.63900733]])

network_7 = pyphi.network_generator.build_network(pyphi.network_generator.UNIT_FUNCTIONS["ising"], rand_7_lc)
subsystem_7 = pyphi.Subsystem(network_7,(0,0,0,0,0,0,0))


# compute
start = time.time()
if subsystem_size == 5:
    phi_structure = pyphi.new_big_phi.phi_structure(subsystem_5)
elif subsystem_size == 6:
    phi_structure = pyphi.new_big_phi.phi_structure(subsystem_6)
elif subsystem_size == 7:
    phi_structure = pyphi.new_big_phi.phi_structure(subsystem_7)
end = time.time()

print("Elapsed time for " + str(subsystem_size) + "-node computation: ")
print(end - start)
print(phi_structure)

