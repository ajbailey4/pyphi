import time
import numpy as np
import ray

#ray.init(num_cpus=4)
ray.init()

@ray.remote
def no_work(a):
    return

start = time.time()
a_id = ray.put(np.zeros((5000, 5000)))
a = np.zeros((5000, 5000))
result_ids = [no_work.remote(a_id) for x in range(10)]
results = ray.get(result_ids)
print("duration =", time.time() - start)


