# slidercalc.py
import math
import traceback
import logging # Use logging for warnings/errors

# Assuming curve.py is in the same directory or accessible via Python path
# Ensure curve.py has the .length fixes applied (using len())
from curve import Bezier, Catmull, point_at_distance as curve_point_at_distance

# Translated from JavaScript to Python by Awlex

def get_end_point(slider_type, slider_length, points):
    """Calculates the endpoint of a slider."""
    # Basic validation
    if not slider_type or slider_length is None or not points or not isinstance(points, list):
        logging.error(f"Invalid input to get_end_point: type={slider_type}, length={slider_length}, points={type(points)}")
        return None # Return None instead of string 'undefined'

    # Ensure slider_length is a number (int or float)
    try:
        slider_length = float(slider_length)
    except (ValueError, TypeError):
         logging.error(f"Invalid slider_length value: {slider_length}")
         return None

    # Ensure points is a list of lists/tuples with numbers
    if not all(isinstance(p, (list, tuple)) and len(p) == 2 and
               all(isinstance(coord, (int, float)) for coord in p) for p in points):
         logging.error(f"Invalid points structure: {points}")
         return None

    slider_type_char = slider_type[0].lower() # Use first char, lowercase

    # --- Linear Slider ---
    if slider_type_char == 'l':
        if len(points) < 2:
            logging.warning("Linear slider needs at least 2 points.")
            return list(points[0]) if len(points)==1 else None
        return point_on_line(points[0], points[1], slider_length)

    # --- Catmull Slider (Legacy) ---
    elif slider_type_char == 'c':
        # Catmull is deprecated. Approximating using Catmull class from curve.py
        logging.warning("Catmull slider type encountered - calculation might be approximated.")
        if len(points) < 2: return None # Catmull needs at least 2 points conceptually
        try:
            catmull_curve = Catmull(points)
            # _calculate_approximations is called in constructor/point_at_distance
            if catmull_curve.pxlength is None: # Check if length calculation worked
                logging.error("Could not calculate Catmull curve length.")
                return None
            # Clamp length
            effective_length = max(0, min(slider_length, catmull_curve.pxlength))
            return catmull_curve.point_at_distance(effective_length)
        except Exception as e:
            logging.error(f"Error calculating Catmull slider endpoint: {e}")
            traceback.print_exc()
            return None

    # --- Bezier Slider ---
    elif slider_type_char == 'b':
        if not points: return None # Need points
        if len(points) == 1: return list(points[0]) # Single point bezier is just the point

        # Handle multi-segment Bezier sliders (red anchor points)
        # The logic involves breaking the point list down where duplicate points indicate segments
        pts_copy = list(points) # Work on a copy
        cumulative_length_processed = 0.0

        while True: # Loop through segments until the target length is reached
            segment_end_index = len(pts_copy)
            # Find the end of the current segment (next red anchor point or end of list)
            for i in range(1, len(pts_copy)):
                if pts_copy[i] == pts_copy[i-1]:
                    segment_end_index = i
                    break

            current_segment_points = pts_copy[:segment_end_index]

            if len(current_segment_points) < 1:
                 logging.error("Bezier processing resulted in empty segment.")
                 return list(points[-1]) if points else None # Fallback

            bezier_segment = Bezier(current_segment_points)
            bezier_segment._calculate_approximations() # Calculate length and points for this segment
            segment_pixel_length = bezier_segment.pxlength

            # Check if length calculation was successful
            if segment_pixel_length is None:
                logging.error(f"Could not calculate length for Bezier segment: {current_segment_points}. Returning last known point.")
                # Fallback: return the start of this failed segment or the absolute end point
                return list(current_segment_points[0]) if current_segment_points else (list(points[-1]) if points else None)


            # Check if the target distance falls within this segment
            # Use tolerance for floating point comparisons
            if cumulative_length_processed + segment_pixel_length >= slider_length - 1e-3:
                remaining_length = slider_length - cumulative_length_processed
                # Clamp remaining_length
                remaining_length = max(0, min(remaining_length, segment_pixel_length))
                # Get the point at the remaining distance along this specific segment
                endpoint = bezier_segment.point_at_distance(remaining_length)
                return endpoint # This is the final endpoint
            else:
                # The target distance is beyond this segment
                cumulative_length_processed += segment_pixel_length
                # Prepare points for the next segment (remove processed segment including the anchor)
                pts_copy = pts_copy[segment_end_index:]
                if not pts_copy:
                    # We've processed all segments, but slider_length was longer than total calculated length
                    logging.warning(f"Slider length {slider_length} exceeds calculated Bezier path length {cumulative_length_processed}. Returning final point.")
                    return list(points[-1]) if points else None # Return absolute last point


    # --- Perfect Circle Slider ---
    elif slider_type_char == 'p':
        if len(points) != 3:
            # Perfect curves require exactly 3 points. Fallback to Bezier.
            logging.warning(f"Pass-through (circular) slider expected 3 points, got {len(points)}. Approximating with Bezier.")
            # Reuse the Bezier logic from above
            if not points: return None
            if len(points) == 1: return list(points[0])
            # Reuse the Bezier logic from above
            if not points: return None
            if len(points) == 1: return list(points[0]) # Single point bezier is just the point

            # Handle multi-segment Bezier sliders (red anchor points)
            pts_copy = list(points) # Work on a copy
            cumulative_length_processed = 0.0

            while True: # Loop through segments until the target length is reached
                segment_end_index = len(pts_copy)
                # Find the end of the current segment (next red anchor point or end of list)
                for i in range(1, len(pts_copy)):
                    if pts_copy[i] == pts_copy[i-1]:
                        segment_end_index = i
                        break

                current_segment_points = pts_copy[:segment_end_index]

                if len(current_segment_points) < 1:
                     logging.error("Bezier processing resulted in empty segment.")
                     return list(points[-1]) if points else None # Fallback

                bezier_segment = Bezier(current_segment_points)
                bezier_segment._calculate_approximations() # Calculate length and points for this segment
                segment_pixel_length = bezier_segment.pxlength

                # Check if length calculation was successful
                if segment_pixel_length is None:
                    logging.error(f"Could not calculate length for Bezier segment: {current_segment_points}. Returning last known point.")
                    # Fallback: return the start of this failed segment or the absolute end point
                    return list(current_segment_points[0]) if current_segment_points else (list(points[-1]) if points else None)

                # Check if the target distance falls within this segment
                # Use tolerance for floating point comparisons
                if cumulative_length_processed + segment_pixel_length >= slider_length - 1e-3:
                    remaining_length = slider_length - cumulative_length_processed
                    # Clamp remaining_length
                    remaining_length = max(0, min(remaining_length, segment_pixel_length))
                    # Get the point at the remaining distance along this specific segment
                    endpoint = bezier_segment.point_at_distance(remaining_length)
                    return endpoint # This is the final endpoint
                else:
                    # The target distance is beyond this segment
                    cumulative_length_processed += segment_pixel_length
                    # Prepare points for the next segment (remove processed segment including the anchor)
                    pts_copy = pts_copy[segment_end_index:]
                    if not pts_copy:
                        # We've processed all segments, but slider_length was longer than total calculated length
                        logging.warning(f"Slider length {slider_length} exceeds calculated Bezier path length {cumulative_length_processed}. Returning final point.")
                        return list(points[-1]) if points else None # Return absolute last point

        p1, p2, p3 = points

        try:
            # Check for collinear points before calculating circumcircle
            # Simplified check: if slopes are equal or vertical line (handles division by zero)
            # Check area of triangle formed by points (0 for collinear) with tolerance
            area = 0.5 * abs(p1[0]*(p2[1]-p3[1]) + p2[0]*(p3[1]-p1[1]) + p3[0]*(p1[1]-p2[1]))
            collinear = area < 1e-6

            if collinear:
                 logging.warning("Pass-through slider points are collinear. Treating as linear.")
                 # Calculate distance along the two linear segments
                 dist1 = distance_points(p1, p2)
                 if slider_length <= dist1:
                      return point_on_line(p1, p2, slider_length)
                 else:
                      # Ensure length doesn't exceed total linear path p1->p2->p3
                      dist2 = distance_points(p2, p3)
                      effective_length = max(0, min(slider_length - dist1, dist2))
                      return point_on_line(p2, p3, effective_length)

            # Points are not collinear, calculate circumcircle
            cx, cy, radius = get_circum_circle(p1, p2, p3)
            if radius < 1e-6: # Check for near-zero radius
                 logging.warning("Pass-through slider has near-zero radius. Treating as linear.")
                 return point_on_line(p1, p3, slider_length) # Treat as line from start to end

            # Calculate angles
            start_angle = math.atan2(p1[1] - cy, p1[0] - cx)
            angle2 = math.atan2(p2[1] - cy, p2[0] - cx)
            end_angle = math.atan2(p3[1] - cy, p3[0] - cx)

            # Determine direction (positive is counter-clockwise)
            # Use cross product logic (same as is_left)
            cross_product_val = ((p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0]))
            direction = 1 if cross_product_val > 0 else -1 # Determine turn direction

            # Calculate required angle delta based on slider length
            angle_delta = slider_length / radius

            # Total angle of the arc from p1 to p3
            total_arc_angle = (end_angle - start_angle)
            # Normalize total_arc_angle based on direction and ensure it's the smaller angle
            while direction * total_arc_angle < -1e-9: total_arc_angle += 2 * math.pi * direction
            while direction * total_arc_angle >= 2 * math.pi - 1e-9: total_arc_angle -= 2 * math.pi * direction

            # Clamp the angle delta to not exceed the total arc angle
            if abs(angle_delta) > abs(total_arc_angle):
                 angle_delta = total_arc_angle
            else:
                 # Ensure the sign matches the direction
                 angle_delta = abs(angle_delta) * direction

            final_angle = start_angle + angle_delta

            # Calculate final coordinates
            final_x = cx + radius * math.cos(final_angle)
            final_y = cy + radius * math.sin(final_angle)
            return [final_x, final_y]

        except ValueError as ve: # Catch collinear error from get_circum_circle
             logging.warning(f"Error calculating circumcircle ({ve}). Treating as linear.")
             dist1 = distance_points(p1, p2)
             if slider_length <= dist1:
                 return point_on_line(p1, p2, slider_length)
             else:
                 dist2 = distance_points(p2, p3)
                 effective_length = max(0, min(slider_length - dist1, dist2))
                 return point_on_line(p2, p3, effective_length)
        except Exception as e:
             logging.error(f"Error calculating Pass-through slider endpoint: {e}")
             traceback.print_exc()
             return None # Return None on error

    else:
        logging.warning(f"Unsupported slider type encountered: '{slider_type}'")
        return None # Return None for unsupported types


# --- Helper Functions (Copied/Adapted from curve.py or original slidercalc) ---

def distance_points(p1, p2):
    """Calculates distance between two points."""
    if not p1 or not p2: return 0.0
    x = (p1[0] - p2[0])
    y = (p1[1] - p2[1])
    return math.sqrt(x * x + y * y)

def point_on_line(p1, p2, length):
    """Calculates a point on the line segment [p1, p2] at a specific length from p1."""
    # Calculate vector from p1 to p2
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    full_length = math.sqrt(dx*dx + dy*dy)

    if full_length < 1e-9: # Points are essentially the same
        return list(p1) # Return a copy of p1

    # Ensure requested length is not negative or greater than segment length
    length = max(0, min(length, full_length))

    # Calculate the ratio of the desired length to the full length
    ratio = length / full_length

    # Calculate the new point coordinates
    x = p1[0] + ratio * dx
    y = p1[1] + ratio * dy
    return [x, y]

def rotate(cx, cy, x, y, radians):
    """Rotates point (x, y) around center (cx, cy) by radians."""
    cos_rad = math.cos(radians)
    sin_rad = math.sin(radians)
    # Translate point back to origin
    temp_x = x - cx
    temp_y = y - cy
    # Rotate point
    rotated_x = temp_x * cos_rad - temp_y * sin_rad
    rotated_y = temp_x * sin_rad + temp_y * cos_rad
    # Translate point back
    final_x = rotated_x + cx
    final_y = rotated_y + cy
    return [final_x, final_y]

def get_circum_circle(p1, p2, p3):
    """Calculates the center (ux, uy) and radius (r) of the circumcircle of p1, p2, p3."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3

    D = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))

    # Check for collinear points (D=0) with tolerance
    if abs(D) < 1e-9:
        raise ValueError("Points are collinear, cannot calculate circumcircle.")

    sq1 = x1*x1 + y1*y1
    sq2 = x2*x2 + y2*y2
    sq3 = x3*x3 + y3*y3
    ux = (sq1 * (y2 - y3) + sq2 * (y3 - y1) + sq3 * (y1 - y2)) / D
    uy = (sq1 * (x3 - x2) + sq2 * (x1 - x3) + sq3 * (x2 - x1)) / D

    dx = ux - x1
    dy = uy - y1
    r = math.sqrt(dx*dx + dy*dy)

    return ux, uy, r

# Add necessary imports if not already present at the top
import logging
import traceback