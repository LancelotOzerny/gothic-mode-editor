"""Small orthographic, depth-buffered UV renderer using only the standard library."""
import math


def project_vertices(vertices, width, height, angle_x, angle_y, zoom):
    axes = tuple(zip(*vertices))
    center = tuple((min(axis) + max(axis)) / 2 for axis in axes)
    radius = max(math.dist(vertex, center) for vertex in vertices)
    scale = min(width, height) * .44 * zoom / max(radius, .001)
    cx, sx = math.cos(angle_x), math.sin(angle_x)
    cy, sy = math.cos(angle_y), math.sin(angle_y)
    projected = []
    for x, y, z in vertices:
        x, y, z = x - center[0], y - center[1], z - center[2]
        x, z = x * cy + z * sy, -x * sy + z * cy
        y, z = y * cx - z * sx, y * sx + z * cx
        projected.append((width / 2 + x * scale, height / 2 - y * scale, z * scale))
    return projected


def sample_texture(texture, u, v):
    """Bilinear repeat sampling; interpolate premultiplied alpha to avoid dark fringes."""
    if texture.width == texture.height == 1:
        return tuple(texture.pixels)
    x, y = (u % 1) * texture.width - .5, (v % 1) * texture.height - .5
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0
    row0, row1 = (y0 % texture.height) * texture.width, ((y0 + 1) % texture.height) * texture.width
    col0, col1 = x0 % texture.width, (x0 + 1) % texture.width
    p, q, r, s = (row0 + col0)*4, (row0 + col1)*4, (row1 + col0)*4, (row1 + col1)*4
    pixels = texture.pixels
    a, b, c, d = (1-fx)*(1-fy), fx*(1-fy), (1-fx)*fy, fx*fy
    if pixels[p+3] == pixels[q+3] == pixels[r+3] == pixels[s+3] == 255:
        return (round(pixels[p]*a + pixels[q]*b + pixels[r]*c + pixels[s]*d),
                round(pixels[p+1]*a + pixels[q+1]*b + pixels[r+1]*c + pixels[s+1]*d),
                round(pixels[p+2]*a + pixels[q+2]*b + pixels[r+2]*c + pixels[s+2]*d), 255)
    a, b, c, d = a*pixels[p+3], b*pixels[q+3], c*pixels[r+3], d*pixels[s+3]
    alpha = a + b + c + d
    if alpha <= 0:
        return (0, 0, 0, 0)
    return (round((pixels[p]*a + pixels[q]*b + pixels[r]*c + pixels[s]*d) / alpha),
            round((pixels[p+1]*a + pixels[q+1]*b + pixels[r+1]*c + pixels[s+1]*d) / alpha),
            round((pixels[p+2]*a + pixels[q+2]*b + pixels[r+2]*c + pixels[s+2]*d) / alpha), round(alpha))


def minification_texture(texture, uv, da_dx, da_dy, db_dx, db_dy):
    """Choose an area-filtered level from the triangle's texel footprint."""
    du_a, du_b = uv[0][0] - uv[2][0], uv[1][0] - uv[2][0]
    dv_a, dv_b = uv[0][1] - uv[2][1], uv[1][1] - uv[2][1]
    footprint = max(math.hypot((du_a*da_dx + du_b*db_dx)*texture.width,
                               (dv_a*da_dx + dv_b*db_dx)*texture.height),
                    math.hypot((du_a*da_dy + du_b*db_dy)*texture.width,
                               (dv_a*da_dy + dv_b*db_dy)*texture.height), 1)
    level = min(len(texture.mipmaps)-1, int(math.log2(footprint)))
    return texture.mipmaps[level]


def render_mesh(mesh, textures, width, height, angle_x, angle_y, zoom=1, textured=True):
    background = bytes((25, 30, 41))
    output = bytearray(background * (width * height))
    depth = [float('-inf')] * (width * height)
    points = project_vertices(mesh.vertices, width, height, angle_x, angle_y, zoom)
    order = sorted(range(len(mesh.faces)), key=lambda i: sum(points[v][2] for v in mesh.faces[i]))
    for index in order:
        a, b, c = (points[v] for v in mesh.faces[index])
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(area) < .01:
            continue
        xmin = max(0, math.floor(min(a[0], b[0], c[0])))
        xmax = min(width - 1, math.ceil(max(a[0], b[0], c[0])))
        ymin = max(0, math.floor(min(a[1], b[1], c[1])))
        ymax = min(height - 1, math.ceil(max(a[1], b[1], c[1])))
        uv = mesh.uvs[index] if index < len(mesh.uvs) else None
        name = mesh.texture_names[index] if index < len(mesh.texture_names) else ''
        texture = textures.get(name) if textured and uv else None
        da_dx, da_dy = (b[1]-c[1])/area, (c[0]-b[0])/area
        db_dx, db_dy = (c[1]-a[1])/area, (a[0]-c[0])/area
        if texture:
            texture = minification_texture(texture, uv, da_dx, da_dy, db_dx, db_dy)
        # A little directional light keeps the solid preview legible.
        ux, uy, uz = (b[i] - a[i] for i in range(3))
        vx, vy, vz = (c[i] - a[i] for i in range(3))
        normal = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        length = math.sqrt(sum(n * n for n in normal)) or 1
        shade = .65 + .35 * abs(normal[2]) / length
        solid = tuple(int(value * shade) for value in (150, 163, 185))
        # Barycentric distance to each edge gives a constant screen-space outline.
        edges = tuple(.75 * math.hypot(p[0]-q[0], p[1]-q[1]) / abs(area)
                      for p, q in ((b, c), (c, a), (a, b)))
        for y in range(ymin, ymax + 1):
            py = y + .5
            crossings = [p[0] + (py-p[1])*(q[0]-p[0])/(q[1]-p[1])
                         for p, q in ((a, b), (b, c), (c, a)) if min(p[1],q[1]) <= py < max(p[1],q[1])]
            if len(crossings) < 2:
                continue
            left = max(xmin, math.ceil(min(crossings)-.5))
            right = min(xmax, math.floor(max(crossings)-.5))
            px = left - .5
            wa = ((b[0]-px)*(c[1]-py) - (b[1]-py)*(c[0]-px))/area
            wb = ((c[0]-px)*(a[1]-py) - (c[1]-py)*(a[0]-px))/area
            for x in range(left, right + 1):
                wa += da_dx
                wb += db_dx
                wc = 1 - wa - wb
                location = y * width + x
                z = wa * a[2] + wb * b[2] + wc * c[2]
                if z < depth[location]:
                    continue
                rgb, alpha = solid, 255
                if texture:
                    u = wa * uv[0][0] + wb * uv[1][0] + wc * uv[2][0]
                    v = wa * uv[0][1] + wb * uv[1][1] + wc * uv[2][1]
                    rgba = sample_texture(texture, u, v)
                    rgb, alpha = rgba[:3], rgba[3]
                elif not textured and (wa < edges[0] or wb < edges[1] or wc < edges[2]):
                    rgb = (53, 65, 83)
                if not alpha:
                    continue
                target = location * 3
                if alpha < 255:
                    rgb = bytes((rgb[i] * alpha + output[target + i] * (255 - alpha)) // 255 for i in range(3))
                output[target:target + 3] = bytes(rgb)
                depth[location] = z
    return bytes(output)
