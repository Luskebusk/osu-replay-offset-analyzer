# curve.py
import math
import operator # Needed for sorting dictionary by key

# Translated from JavaScript to Python by Awlex

def is_point_in_circle(point, center, radius):
    return distance_points(point, center) <= radius

def distance_points(p1, p2):
    x = (p1[0] - p2[0])
    y = (p1[1] - p2[1])
    return math.sqrt(x * x + y * y)

def distance_from_points(array):
    distance = 0
    # Use standard Python loop
    for i in range(1, len(array)):
        distance += distance_points(array[i], array[i - 1])
    return distance

def angle_from_points(p1, p2):
    # Ensure points are not identical to avoid atan2(0,0)
    if p1[0] == p2[0] and p1[1] == p2[1]:
        return 0.0 # Or handle as an error/default angle
    return math.atan2(p2[1] - p1[1], p2[0] - p1[0])

def cart_from_pol(r, teta):
    x2 = (r * math.cos(teta))
    y2 = (r * math.sin(teta))
    return [x2, y2]

def point_at_distance(array, distance):
    # needs a serious cleanup ! -- Keeping original logic structure
    # Removed global declarations as they weren't used properly
    current_distance = 0
    target_index = 0 # Use a more descriptive name than 'i' from outer scope

    if not array or len(array) < 2: # Check if list exists and has at least 2 points
        return [0, 0, 0, 0] # Return default/error value

    total_dist = distance_from_points(array)

    if distance <= 0:
        angle = angle_from_points(array[0], array[1])
        return [array[0][0], array[0][1], angle, 0]

    # Use len() instead of .length
    if total_dist <= distance:
        angle = angle_from_points(array[len(array) - 2], array[len(array) - 1])
        return [array[len(array) - 1][0],
                array[len(array) - 1][1], # CORRECTED: Use len()
                angle,
                len(array) - 2]           # CORRECTED: Use len()

    # Find the segment where the distance lies
    for i in range(len(array) - 1): # Iterate up to second-to-last point
        segment_length = distance_points(array[i], array[i+1])

        if distance <= current_distance + segment_length:
            target_index = i
            # Calculate remaining distance needed within this segment
            remaining_dist = distance - current_distance
            angle = angle_from_points(array[i], array[i + 1])

            if remaining_dist == 0: # Exactly at the start of the segment
                 coord = [array[i][0], array[i][1]]
            else: # Point lies within the segment
                 cart = cart_from_pol(remaining_dist, angle)
                 # Calculate position by adding vector from start point
                 coord = [(array[i][0] + cart[0]), (array[i][1] + cart[1])]

            return [coord[0], coord[1], angle, target_index]

        current_distance += segment_length

    # Fallback if something went wrong (should technically be covered by total_dist check)
    # Return the last point
    last_idx = len(array) - 1
    angle = angle_from_points(array[last_idx - 1], array[last_idx])
    return [array[last_idx][0], array[last_idx][1], angle, last_idx -1]


def cpn(p, n):
    if p < 0 or p > n:
        return 0
    # Avoid division by zero if p=0
    if p == 0 or p == n:
        return 1
    if p > n // 2:
         p = n - p # Optimization

    # More stable calculation for combinations
    res = 1
    for i in range(p):
        res = res * (n - i) // (i + 1)
    return res

# --- CORRECTED array_values ---
# This function needs to handle the dictionary from Bezier.pos
# It should return a list of the dictionary's values, ordered by the keys (t)
def array_values(pos_dict):
    if not isinstance(pos_dict, dict):
        # If it's already a list or other iterable, just return it as a list
        # This might happen if called from Catmull which uses a list
        try:
            return list(pos_dict)
        except TypeError:
            return [] # Return empty list if not iterable

    if not pos_dict:
        return []
    # Sort the dictionary items by key (time 't') and return only the values (points)
    sorted_items = sorted(pos_dict.items(), key=operator.itemgetter(0))
    return [item[1] for item in sorted_items]
# --- END CORRECTION ---

def array_calc(op, array1, array2):
    minimum = min(len(array1), len(array2))
    retour = []
    # Assuming op is '*' or '+'? Needs clarification or safer implementation
    # This function seems unused based on search in curve.py/slidercalc.py,
    # but left as is for now. It might be safer to raise an error if op is unexpected.
    for i in range(minimum):
        if op == '*':
             retour.append(array1[i] * array2[i]) # Example, assuming multiplication
        elif op == '+':
             retour.append(array1[i] + array2[i]) # Example, assuming addition
        else:
             # Defaulting to addition, or could raise ValueError
             retour.append(array1[i] + array2[i])

    return retour

# ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** *

class Bezier:
    def __init__(self, points):
        self.points = points
        self.order = len(points) # Correct use of len()

        self.step = (0.0025 / self.order) if self.order > 0 else 1
        self.pos = {} # Dictionary to store calculated points {t: [x, y]}
        self.pxlength = None # Initialize length cache
        self.approximation_points = None # Initialize point list cache

    def at(self, t):
        # B(t) = sum_(i=0) ^ n(C(n,i)) * (1 - t) ^ (n - i) * t ^ i * P_i
        # Removed caching within 'at' as it interfered with recalculation logic
        # if t in self.pos:
        #     return self.pos[t]

        x = 0.0 # Use floats
        y = 0.0 # Use floats
        n = self.order - 1

        if n < 0: # Handle case with no points
             return [0.0, 0.0]
        if n == 0: # Handle case with one point
             return list(self.points[0]) # Return a copy

        # Calculate Bernstein polynomial
        for i in range(n + 1):
            bernstein_coeff = cpn(i, n) * ((1 - t) ** (n - i)) * (t ** i)
            x += bernstein_coeff * self.points[i][0]
            y += bernstein_coeff * self.points[i][1]

        # Store calculated point if needed elsewhere, but 'at' primarily returns it
        # self.pos[t] = [x, y]

        return [x, y]

    # Changed to approximate length and store points
    def _calculate_approximations(self):
        # If already calculated, return
        if self.approximation_points is not None:
            return

        self.pos = {} # Clear previous points before recalculating
        self.pxlength = 0.0
        calculated_points = []

        if self.order <= 0:
             self.approximation_points = []
             return

        prev = self.at(0.0)
        self.pos[0.0] = prev
        calculated_points.append(prev)
        t = self.step # Start from the first step

        # Iterate up to and including t=1.0
        while t <= 1.0 + (self.step / 2): # Use tolerance for float comparison
            # Clamp t to 1.0 if it slightly overshoots
            current_t = min(t, 1.0)
            current = self.at(current_t)
            self.pxlength += distance_points(prev, current)
            self.pos[current_t] = current
            calculated_points.append(current)
            prev = current
            t += self.step
            # Ensure the final point at t=1.0 is calculated if steps don't land on it
            if t > 1.0 and current_t < 1.0:
                 t = 1.0

        self.approximation_points = calculated_points

    def point_at_distance(self, dist):
        self._calculate_approximations() # Ensure points and length are calculated
        # Handle edge cases
        if self.order <= 0:
            return [0.0, 0.0]
        if self.order == 1:
            return list(self.points[0]) # Return a copy

        # Use the point_at_distance function with the calculated approximation points
        # Return only the first two elements (x, y)
        result_point = point_at_distance(self.approximation_points, dist)
        return result_point[:2]

# ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** ** * #
# Catmull class remains largely unchanged, check array_values usage
class Catmull:
    def __init__(self, points):
        self.points = points
        self.order = len(points) # Correct use of len()
        self.step = 0.025
        self.pos = [] # Catmull uses a list directly
        self.pxlength = None
        self._calculate_approximations()

    def at(self, x, t):
        # Ensure x is within valid range
        if x < 0 or x >= self.order:
             return [0.0, 0.0] # Or raise error

        # Handle boundary points for Catmull-Rom spline
        p0 = self.points[x - 1] if x >= 1 else self.points[0] # Repeat first point if x=0
        p1 = self.points[x]
        p2 = self.points[x + 1] if x + 1 < self.order else self.points[self.order - 1] # Repeat last point
        p3 = self.points[x + 2] if x + 2 < self.order else self.points[self.order - 1] # Repeat last point

        retour = [0.0, 0.0]
        t2 = t * t
        t3 = t2 * t

        # Catmull-Rom spline formula
        for i in range(2): # Iterate for x and y coordinates
            retour[i] = 0.5 * (
                (2 * p1[i]) +
                (-p0[i] + p2[i]) * t +
                (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t2 +
                (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t3
            )
        return retour

    def _calculate_approximations(self):
        if self.pos: # Check if list is already populated
            return

        self.pxlength = 0.0
        if self.order <= 1:
            self.pos = list(self.points) # Copy points if 0 or 1
            return

        prev = self.points[0] # Start with the first control point
        self.pos.append(prev)
        num_steps = int(1.0 / self.step) # Number of steps per segment

        # Iterate through the segments defined by control points
        for i in range(self.order - 1):
            # Generate points within the segment using Catmull-Rom formula
            for j in range(1, num_steps + 1):
                 t = j * self.step
                 current = self.at(i, t)
                 self.pxlength += distance_points(prev, current)
                 self.pos.append(current)
                 prev = current

    def point_at_distance(self, dist):
        self._calculate_approximations() # Ensure points and length are calculated
        # Handle edge cases
        if self.order <= 0:
            return [0.0, 0.0]
        if self.order == 1:
            return list(self.points[0])

        # Use the point_at_distance function with the calculated approximation points
        result_point = point_at_distance(self.pos, dist) # Pass the list self.pos
        return result_point[:2]