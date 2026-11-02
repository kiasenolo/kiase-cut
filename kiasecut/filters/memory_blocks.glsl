// @filter 記憶體花屏（分塊）
// @category 風格
// @description 像顯示記憶體壞掉的花屏：畫面裂成一格一格大小固定的分塊（有橫向的趨勢），輪廓還看得出來，但每一塊各有各的下場——邊緣雜訊、只剩色彩、混沌雜點、隨機色彩、座標只剩 X 或 Y、座標走到一半就斷掉、或已經消失，每一種的比例都可以調
// @param amount float 1 0 1 "損壞程度"
// @param spread bool true "隨時間擴大"
// @param blk float 40 8 512 "分塊高度（像素）"
// @param aspect float 3 1 16 "分塊寬高比"
// @param trend float 0.6 0 1 "橫向連動"
// @param split float 0.4 0 0.9 "細分"
// @param levels int 4 1 6 "分塊重數"
// @param rate float 60 0 240 "每秒變化（0：不動）"
// @param seed float 0 0 100 "種子"
// @param gone_look menu 黑色 "黑色|透明|白色" "消失的分塊"
// @panel 分塊種類（比例）
// @param w_edge float 0.02 0 1 "邊緣雜訊（交界處輪廓特別重）"
// @param w_color float 0.05 0 1 "只剩色彩"
// @param w_snow float 0.13 0 1 "混沌：雜點"
// @param w_streak float 0.05 0 1 "混沌：直條紋"
// @param w_dither float 0.13 0 1 "混沌：抖動殘影"
// @param w_random float 0.25 0 1 "隨機色彩（輪廓還在）"
// @param w_vx float 0.06 0 1 "只剩 X（往下拉成直條）"
// @param w_vy float 0.06 0 1 "只剩 Y（往右拉成橫條）"
// @param w_cutx float 0.03 0 1 "X 走到一半斷掉"
// @param w_cuty float 0.03 0 1 "Y 走到一半斷掉"
// @param w_cutxy float 0.02 0 1 "X、Y 都走到一半斷掉"
// @param w_gone float 0.1 0 1 "消失"

// The picture is cut into blocks of one fixed size (blk high, aspect times as wide - the rows
// lie flat; `trend` makes the blocks along a row fail and fail alike, as a run of memory does).
// Each cell is split again into halves of the same shape, up to `levels` deep (`split` says
// how likely). Each block fails at its own moment (spread: over the effect's length; neighbours
// tend to fail together, as one chip) and becomes one of the kinds below, by the weights:
//   edge      a little noise over a dim base colour, with a heavy outline where the colours change fast
//             (the stronger the change, the heavier the line; a soft change leaves a faint one)
//   color     only its colour: the block's average, the outline gone
//   snow      dark blue with bright specks, more of them where the picture is bright (the outline shows a little)
//   streak    columns of colour that repeat down the block
//   dither    the picture from elsewhere cut to a few bits
//   random    the colours random (a hue, and a noise tint) but the outline (the brightness) stays
//   vx        the picture's vector only has X: each column shows the block's first row
//   vy        only Y: each row shows the block's first column
//   cutx/y/xy the coordinate runs along the block and stops half way: what is left is smeared
//   gone      black / transparent / white
// The noise changes `rate` times a second.

float h1(float a, float b) { return fract(sin(a * 12.9898 + b * 78.233 + seed * 1.731) * 43758.5453); }
float hp(vec2 p, float k) {                                 // a speck's random value (no diagonal pattern)
    vec3 q = fract(vec3(p.xyx) * 0.1031 + vec3(k * 0.137 + seed * 0.071));
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}


vec3 hue_turn(vec3 c, float a) {
    const vec3 k = vec3(0.57735);
    float ca = cos(a), sa = sin(a);
    return c * ca + cross(k, c) * sa + k * dot(k, c) * (1.0 - ca);
}

vec4 at(vec2 p) { return src((clamp(floor(p), vec2(0.0), resolution - 1.0) + 0.5) / resolution); }

vec4 effect(vec2 uv) {
    vec2 px = floor(uv * resolution);
    float cover = clamp(amount, 0.0, 1.0) * (spread ? clamp(progress * 1.15, 0.0, 1.0) : 1.0);
    float tick = floor(time * rate);

    // the block this pixel is in
    float size = max(blk, 4.0);
    vec2 cs = vec2(size * aspect, size);
    vec2 cell = floor(px / cs);
    for (int i = 1; i < 6; i++) {
        if (i >= levels || size < 8.0 || h1(cell.x + cell.y * 211.0 + float(i) * 977.0, 41.0) >= split) break;
        size *= 0.5;
        cs = vec2(size * aspect, size);
        cell = floor(px / cs);
    }
    float id = cell.x + cell.y * 4099.0 + size * 7.0;
    // a run along the row: cells of the row that share a fate
    float run = 1.0 + floor(h1(cell.y + size * 3.0, 46.0) * trend * 10.0);
    float gid = floor(cell.x / run) + cell.y * 4099.0 + size * 7.0 + 0.5;
    float own = (h1(id, 47.0) < trend) ? gid : id;

    // when it fails: part its own, part its chip's (a few big blocks' worth)
    vec2 chip = floor(px / (max(blk, 4.0) * vec2(aspect, 1.0) * 4.0));
    float fail = 0.6 * h1(own, 43.0) + 0.4 * h1(chip.x + chip.y * 313.0, 44.0);
    float w[12] = float[12](w_edge, w_color, w_snow, w_streak, w_dither, w_random,
                            w_vx, w_vy, w_cutx, w_cuty, w_cutxy, w_gone);
    float wsum = 0.0;
    for (int i = 0; i < 12; i++) wsum += w[i];
    if (fail >= cover || wsum <= 0.0) return src(uv);

    float s = h1(own, 45.0) * wsum;
    int kind = 11;
    for (int i = 0; i < 12; i++) {
        if (s < w[i]) { kind = i; break; }
        s -= w[i];
    }
    vec2 o = cell * cs;                                     // the block's corner
    vec2 d = px - o;                                        // where in it

    if (kind == 0) {                                        // noise with the outline drawn heavy at the colour changes
        vec4 c = unpremultiply(at(px));
        vec3 gx = unpremultiply(at(px + vec2(2.0, 0.0))).rgb - unpremultiply(at(px - vec2(2.0, 0.0))).rgb;
        vec3 gy = unpremultiply(at(px + vec2(0.0, 2.0))).rgb - unpremultiply(at(px - vec2(0.0, 2.0))).rgb;
        float g = length(gx) + length(gy);                  // how fast the colour changes here
        float line = smoothstep(0.08, 0.7, g);
        line *= line * (3.0 - 2.0 * line) * 1.15;           // a soft change stays faint, a hard one is heavy
        vec2 t = px + vec2(tick * 17.0, tick * 31.0);
        vec3 noise = vec3(hp(t, 80.0), hp(t, 81.0), hp(t, 82.0));
        vec3 base = c.rgb * 0.35 + vec3(0.03, 0.05, 0.14);  // a little of the colour, on a dark blue base
        vec3 col = base + (noise - 0.5) * 0.14;             // a little noise
        vec3 edge = mix(c.rgb, vec3(1.0), 0.45) * (0.6 + 0.8 * noise);   // the line: the colour, with noise in it
        return vec4(clamp(mix(col, edge, clamp(line, 0.0, 1.0)), 0.0, 1.0), 1.0);
    }

    if (kind == 1) {                                        // only the colour
        vec4 sum = vec4(0.0);
        for (int j = 0; j < 4; j++)
            for (int i = 0; i < 4; i++)
                sum += at(o + (vec2(i, j) + 0.5) * 0.25 * cs);
        return sum / 16.0;
    }

    if (kind <= 4) {                                        // chaos
        float g = (h1(id, 50.0) < 0.5) ? 1.0 : 2.0;        // a speck's size
        vec2 q = floor(px / g);
        vec2 t = q + vec2(tick * 17.0, tick * 31.0);
        vec3 col;
        if (kind == 2) {                                    // snow: dark blue, bright specks of every colour
            vec3 n = vec3(hp(t, 52.0), hp(t, 53.0), hp(t, 54.0));
            vec4 u = unpremultiply(at(px));                 // the outline: bright places get more, brighter specks
            float lum = dot(u.rgb, vec3(0.299, 0.587, 0.114));
            col = step(vec3(0.8 + 0.12 * h1(id, 55.0) - 0.22 * lum), n);
            if (col == vec3(0.0)) col = vec3(0.05, 0.08, 0.28) * (0.4 + 1.2 * n.x) * (0.45 + 1.4 * lum);
        } else if (kind == 3) {                             // streaks: columns that repeat down the block
            float per = 1.0 + floor(h1(id, 56.0) * 6.0);
            float cx = floor(q.x / per);
            vec3 n = vec3(h1(cx + id, 57.0 + tick), h1(cx * 1.3 + id, 58.0 + tick), h1(cx * 2.1 + id, 59.0 + tick));
            float row = h1(floor(q.y / (1.0 + floor(h1(id, 60.0) * 4.0))) + id, 61.0 + tick);
            col = mix(step(vec3(0.5), n), vec3(row), 0.3 * step(0.7, row));
        } else {                                            // the picture dithered to a few bits, from elsewhere
            vec2 off = floor((vec2(h1(id, 62.0), h1(id, 63.0)) - 0.5) * 2.0 * 0.4 * resolution);
            vec4 c = unpremultiply(at(mod(floor(px / (g * 3.0)) * (g * 3.0) + off, resolution)));
            vec3 n = vec3(hp(t, 64.0), hp(t, 65.0), hp(t, 66.0));
            col = step(n, c.rgb * c.rgb * 0.9);
            if (col == vec3(0.0)) col = vec3(0.04, 0.07, 0.25);
        }
        return vec4(col, 1.0);
    }

    if (kind == 5) {                                        // random colours, the outline stays
        vec4 c = unpremultiply(src(uv));
        float lum = dot(c.rgb, vec3(0.299, 0.587, 0.114));
        vec3 base = hue_turn(vec3(1.0, 0.25, 0.1), 6.2831853 * h1(own, 70.0));
        vec2 t = px + vec2(tick * 17.0, tick * 31.0);
        vec3 noise = vec3(hp(t, 71.0), hp(t, 72.0), hp(t, 73.0));
        vec3 tint = mix(base, noise * 1.4, 0.3);
        // the outline: the brightness with its contrast raised, and the edges drawn over it
        float l2 = dot(unpremultiply(at(px + vec2(2.0, 0.0))).rgb, vec3(0.299, 0.587, 0.114));
        float l3 = dot(unpremultiply(at(px + vec2(0.0, 2.0))).rgb, vec3(0.299, 0.587, 0.114));
        float edge = clamp((abs(lum - l2) + abs(lum - l3)) * 3.0, 0.0, 1.0);
        float shade = clamp((lum - 0.5) * 2.2 + 0.5, 0.0, 1.0);
        return premultiply(vec4(clamp(tint * (0.08 + 1.5 * shade) * (1.0 - 0.7 * edge) + edge * 0.15, 0.0, 1.0), c.a));
    }

    if (kind <= 7) {                                        // the vector has only X, or only Y
        return (kind == 6) ? at(vec2(px.x, o.y)) : at(vec2(o.x, px.y));
    }

    // the coordinate runs along the block and stops half way
    float cut = 0.15 + 0.7 * h1(own, 74.0);
    vec2 p = px;
    if (kind == 8 || kind == 10) p.x = o.x + min(d.x, cs.x * cut);
    if (kind == 9 || kind == 10) p.y = o.y + min(d.y, cs.y * cut);
    if (kind <= 10) return at(p);

    // gone
    if (gone_look == 1) return vec4(0.0);
    if (gone_look == 2) return vec4(1.0);
    return vec4(0.0, 0.0, 0.0, 1.0);
}
