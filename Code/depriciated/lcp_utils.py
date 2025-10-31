import numpy as np
from skimage.graph import MCP_Geometric # Use the correct class

def process_single_node(start_node, all_nodes, resistance_array, start_index, node_count):
    """
    Worker function to be run in parallel.
    Calculates all paths from ONE start_node to all other nodes.
    """
    # Create an empty traffic array *for this worker only*
    worker_traffic_array = np.zeros(resistance_array.shape, dtype=np.int32)
    
    # Initialize MCP_Geometric for this start node
    mcp = MCP_Geometric(resistance_array, fully_connected=True)

    # Calculate the cost surface ONCE from this start_node
    try:
        cost_surface = mcp.find_costs(starts=[start_node])
    except Exception as e:
        # print(f"Worker {start_index}: Could not process {start_node}: {e}")
        return worker_traffic_array # Return the empty array
        
    # This inner loop is fast
    for j in range(start_index + 1, node_count):
        end_node = all_nodes[j]
        
        try:
            # Use the cheap .traceback() function
            indices, cost = mcp.traceback(end_node)
            
            # Add this path to our traffic map
            if indices:
                rows, cols = zip(*indices)
                worker_traffic_array[rows, cols] += 1
                
        except Exception as e:
            continue
            
    return worker_traffic_array