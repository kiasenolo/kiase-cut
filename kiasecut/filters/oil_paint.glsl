// @filter 油畫
// @category 風格
// @description 照 Blender 的「Kuwahara」節點：細節抹平成一塊塊筆觸，邊緣仍然清楚。經典：像素四周四個方塊，取顏色最平均的那一塊的平均；各向異性：順著邊緣的方向取橢圓形，分八個扇形，顏色越平均的扇形占越多（均勻度是結構張量的模糊大小，銳利度是扇形之間的差距，偏心率是橢圓的細長程度）。Blender 的「高精度」只是換一種算法，這裡一律用精確的算法，所以沒有這個選項
// @passes 4
// @precision float
// @skip 0-2 kind == 經典
// @param size float 6 0 100 "大小"
// @param kind menu 各向異性 "經典|各向異性" "類型"
// @param uniformity int 4 0 50 "均勻度"
// @param sharpness float 1 0 1 "銳利度"
// @param eccentricity float 1 0 2 "偏心率"
// @enable uniformity kind == 各向異性
// @enable sharpness kind == 各向異性
// @enable eccentricity kind == 各向異性

// Source: the Kuwahara node of Blender's compositor (compositor_kuwahara_classic.glsl, _anisotropic_compute_structure_tensor.glsl,
// _anisotropic.glsl), rewritten for KiaseCut; the structure tensor is smoothed with the Gaussian of the Blur node,
// as Blender does. A pixel is a pixel of the canvas. A big size reads only some of the pixels of the square / ellipse
// (at most about 32 on a side), the way the other big filters do.
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

const int CAP = 32;
const float PI = 3.14159265358979;

float sq(float x) { return x * x; }
vec2 sq(vec2 x) { return x * x; }

// the picture the filter was given, one pixel (i, j) from this one (the nearest pixel at the edge)
vec4 at(vec2 uv, vec2 o) { return original(uv + o / resolution); }

// pass 0: structure tensor (dx.dx, dx.dy, dx.dy, dy.dy) of the colour, Blender's Sobel-like kernel
vec4 tensor(vec2 uv) {
    const float corner = 0.182, centre = 1.0 - 2.0 * corner;
    vec3 dx = at(uv, vec2(-1, 1)).rgb * -corner + at(uv, vec2(-1, 0)).rgb * -centre + at(uv, vec2(-1, -1)).rgb * -corner
            + at(uv, vec2(1, 1)).rgb * corner + at(uv, vec2(1, 0)).rgb * centre + at(uv, vec2(1, -1)).rgb * corner;
    vec3 dy = at(uv, vec2(-1, 1)).rgb * corner + at(uv, vec2(0, 1)).rgb * centre + at(uv, vec2(1, 1)).rgb * corner
            + at(uv, vec2(-1, -1)).rgb * -corner + at(uv, vec2(0, -1)).rgb * -centre + at(uv, vec2(1, -1)).rgb * -corner;
    return vec4(dot(dx, dx), dot(dx, dy), dot(dx, dy), dot(dy, dy));
}

// passes 1, 2: the tensor smoothed along dir with Blender's Gaussian, size uniformity (weights exp(-4.5 (i / size)^2), ceil(size) each side)
vec4 smooth_tensor(vec2 uv, vec2 dir) {
    float u = float(uniformity);
    if (u <= 0.0) return src(uv);
    int n = int(ceil(u));
    float stride = max(1.0, ceil(float(n) / 96.0));
    vec4 acc = src(uv);
    float total = 1.0;
    for (int j = 1; j <= 96; j++) {
        float i = float(j) * stride;
        if (i > float(n)) break;
        float w = exp(-4.5 * sq(i / u));
        acc += w * (src(uv + dir * i / resolution) + src(uv - dir * i / resolution));
        total += 2.0 * w;
    }
    return acc / total;
}

// pass 3, classic: of the four squares (size + 1 pixels on a side) that have this pixel for a corner, the mean of the one
// whose colour varies least (pixels outside the picture are left out of the mean)
vec4 classic(vec2 uv) {
    int radius = max(0, int(size));
    float stride = max(1.0, ceil(float(radius + 1) / float(CAP)));
    vec2 pix = floor(uv * resolution);
    float least = 1e30;
    vec4 best = original(uv);
    for (int q = 0; q < 4; q++) {
        vec2 sgn = vec2(float(q % 2) * 2.0 - 1.0, float(q / 2) * 2.0 - 1.0);
        vec4 sum = vec4(0.0), sum2 = vec4(0.0);
        float count = 0.0;
        for (int j = 0; j < CAP; j++) {
            float y = float(j) * stride;
            if (y > float(radius)) break;
            for (int i = 0; i < CAP; i++) {
                float x = float(i) * stride;
                if (x > float(radius)) break;
                vec2 p = pix + vec2(x, y) * sgn;
                if (p.x < 0.0 || p.y < 0.0 || p.x >= resolution.x || p.y >= resolution.y) continue;
                vec4 c = at(uv, vec2(x, y) * sgn);
                sum += c;
                sum2 += c * c;
                count += 1.0;
            }
        }
        vec4 mean = sum / count, var = sum2 / count - mean * mean;
        float v = var.r + var.g + var.b;
        if (v < least) {
            least = v;
            best = mean;
        }
    }
    return best;
}

vec4 anisotropic(vec2 uv) {
    vec4 st = src(uv);                                       // (the smoothed tensor)
    float dxdx = st.x, dxdy = st.y, dydy = st.w;
    float lam_a = (dxdx + dydy) / 2.0;
    float lam_b = sqrt(sq(dxdx - dydy) + 4.0 * sq(dxdy)) / 2.0;
    float first = lam_a + lam_b, second = lam_a - lam_b;
    vec2 ev = vec2(first - dxdx, -dxdy);
    float evl = length(ev);
    vec2 unit_ev = evl != 0.0 ? ev / evl : vec2(0.0, 1.0);          // (no direction: as Blender's result shows, along y)
    float sum_ev = first + second;
    float anisotropy = sum_ev > 0.0 ? (first - second) / sum_ev : 0.0;
    float radius = max(0.0, size);
    if (radius == 0.0) return original(uv);

    float width_factor = 1.0 + eccentricity * anisotropy;      // (Blender: (e + anisotropy) / e with e = 1 / the eccentricity socket)
    float ew = width_factor * radius, eh = radius / width_factor;
    float cs = unit_ev.x, sn = unit_ev.y;
    mat2 inv_ellipse = mat2(cs / ew, -sn / eh, sn / ew, cs / eh);    // (GLSL's mat2 takes its columns, as Blender's float2x2 does)
    vec2 major = ew * unit_ev, minor = eh * unit_ev.yx * vec2(-1.0, 1.0);
    vec2 bounds = ceil(sqrt(sq(major) + sq(minor)));
    float stride = max(1.0, ceil(max(bounds.x, bounds.y) / float(CAP)));

    const int SECTORS = 8;
    float centre_overlap = 2.0 / radius;
    float envelope = (1.5 * PI) / float(SECTORS);
    float cross_overlap = (centre_overlap + cos(envelope)) / sq(sin(envelope));

    vec4 mean_c[8], mean_c2[8];
    float wsum[8];
    vec4 centre = original(uv);
    float centre_w = 1.0 / float(SECTORS) / (stride * stride);
    for (int k = 0; k < SECTORS; k++) {
        mean_c[k] = centre * centre_w;
        mean_c2[k] = centre * centre * centre_w;
        wsum[k] = centre_w;
    }
    for (int jj = 0; jj <= CAP; jj++) {
        float j = float(jj) * stride;
        if (j > bounds.y) break;
        for (int ii = -CAP; ii <= CAP; ii++) {
            float i = float(ii) * stride;
            if (abs(i) > bounds.x) continue;
            if (jj == 0 && ii <= 0) continue;
            vec2 dp = inv_ellipse * vec2(i, j);
            float len2 = dot(dp, dp);
            if (len2 > 1.0) continue;
            float sw[8];
            vec2 poly = centre_overlap - cross_overlap * sq(dp);
            sw[0] = sq(max(0.0, dp.y + poly.x));
            sw[2] = sq(max(0.0, -dp.x + poly.y));
            sw[4] = sq(max(0.0, -dp.y + poly.x));
            sw[6] = sq(max(0.0, dp.x + poly.y));
            vec2 rp = 0.70710678118 * vec2(dp.x - dp.y, dp.x + dp.y);
            vec2 rpoly = centre_overlap - cross_overlap * sq(rp);
            sw[1] = sq(max(0.0, rp.y + rpoly.x));
            sw[3] = sq(max(0.0, -rp.x + rpoly.y));
            sw[5] = sq(max(0.0, -rp.y + rpoly.x));
            sw[7] = sq(max(0.0, rp.x + rpoly.y));
            float sws = sw[0] + sw[1] + sw[2] + sw[3] + sw[4] + sw[5] + sw[6] + sw[7];
            float radial = exp(-PI * len2) / sws;
            vec4 up = at(uv, vec2(i, j)), lo = at(uv, -vec2(i, j));
            vec4 up2 = up * up, lo2 = lo * lo;
            for (int k = 0; k < SECTORS; k++) {
                float w = sw[k] * radial;
                wsum[k] += w;
                mean_c[k] += up * w;
                mean_c2[k] += up2 * w;
                int other = (k + SECTORS / 2) % SECTORS;
                wsum[other] += w;
                mean_c[other] += lo * w;
                mean_c2[other] += lo2 * w;
            }
        }
    }
    float total = 0.0;
    vec4 acc = vec4(0.0);
    for (int k = 0; k < SECTORS; k++) {
        vec4 m = mean_c[k] / wsum[k], m2 = mean_c2[k] / wsum[k];
        vec4 variance = abs(m2 - m * m);
        float sd = dot(sqrt(variance.rgb), vec3(1.0));
        float w = 1.0 / pow(max(0.02, sd), 16.0 * sharpness * sharpness);   // (the socket's 0 - 1 reaches Blender's shader as 16 x square)
        total += w;
        acc += m * w;
    }
    return total == 0.0 ? centre : acc / total;
}

vec4 effect(vec2 uv) {
    if (pass_index == 0) return tensor(uv);
    if (pass_index == 1) return smooth_tensor(uv, vec2(1.0, 0.0));
    if (pass_index == 2) return smooth_tensor(uv, vec2(0.0, 1.0));
    return kind == 0 ? classic(uv) : anisotropic(uv);
}
