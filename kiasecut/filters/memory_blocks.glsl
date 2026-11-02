// @filter 記憶體花屏（分塊）
// @category 風格
// @description 像顯示記憶體壞掉的花屏：畫面裂成大小不一的分塊（橫向的比較多），輪廓還看得出來，但每一塊各有各的下場——有的保留原樣，有的只剩原本的顏色，有的充滿混沌的雜點，有的已經消失
// @param amount float 1 0 1 "損壞程度"
// @param spread bool true "隨時間擴大"
// @param blk float 96 8 512 "分塊大小（像素）"
// @param split float 0.5 0 0.9 "細分"
// @param stretch float 0.5 0 1 "橫向拉長"
// @param w_keep float 0.25 0 1 "保留原樣"
// @param w_color float 0.3 0 1 "只剩色彩"
// @param w_chaos float 0.3 0 1 "混沌"
// @param w_gone float 0.15 0 1 "消失"
// @param gone_look menu 黑色 "黑色|透明|白色" "消失的分塊"
// @param rate float 30 0 240 "每秒變化（0：不動）"
// @param seed float 0 0 100 "種子"

// The picture is cut into blocks the way a broken frame buffer shows it: a grid of `blk` pixels,
// each cell split again (up to three times, `split` says how likely) into halves, and a row of
// cells can be wider (`stretch`) - so blocks of every size lie in rows. Each block fails at its
// own moment (spread: over the effect's length; neighbours tend to fail together, as one chip)
// and then becomes one of four things, by the weights: it stays as it was; it keeps only its
// colour (the block's average, the outline gone); it fills with noise (dark blue with bright
// specks, streaks, or the picture dithered to a few bits); or it is gone. The noise changes
// `rate` times a second.

float h1(float a, float b) { return fract(sin(a * 12.9898 + b * 78.233 + seed * 1.731) * 43758.5453); }
float hp(vec2 p, float k) {                                 // a speck's random value (no diagonal pattern)
    vec3 q = fract(vec3(p.xyx) * 0.1031 + vec3(k * 0.137 + seed * 0.071));
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}

vec4 effect(vec2 uv) {
    vec2 px = floor(uv * resolution);
    float cover = clamp(amount, 0.0, 1.0) * (spread ? clamp(progress * 1.15, 0.0, 1.0) : 1.0);
    float tick = floor(time * rate);

    // the block this pixel is in
    float size = max(blk, 4.0);
    vec2 cs = vec2(size);
    vec2 cell = vec2(0.0);
    for (int i = 0; i < 4; i++) {
        float lv = float(i);
        float wm = 1.0 + floor(h1(floor(px.y / size) + lv * 57.0, 40.0) * stretch * 8.0);
        cs = vec2(size * wm, size);
        cell = floor(px / cs);
        if (i == 3 || size < 8.0 || h1(cell.x + cell.y * 211.0 + lv * 977.0, 41.0) >= split) break;
        size *= 0.5;
    }
    float id = cell.x + cell.y * 4099.0 + size * 7.0;

    // when it fails: part its own, part its chip's (a few big blocks' worth)
    vec2 chip = floor(px / (max(blk, 4.0) * 4.0));
    float fail = 0.6 * h1(id, 43.0) + 0.4 * h1(chip.x + chip.y * 313.0, 44.0);
    float wsum = w_keep + w_color + w_chaos + w_gone;
    if (fail >= cover || wsum <= 0.0) return src(uv);

    float s = h1(id, 45.0) * wsum;
    if (s < w_keep) return src(uv);

    if (s < w_keep + w_color) {                             // only the colour: the block's average
        vec4 sum = vec4(0.0);
        vec2 o = cell * cs;
        for (int j = 0; j < 4; j++)
            for (int i = 0; i < 4; i++)
                sum += src((min(o + (vec2(i, j) + 0.5) * 0.25 * cs, resolution - 0.5)) / resolution);
        return sum / 16.0;
    }

    if (s < w_keep + w_color + w_chaos) {                   // chaos
        float g = (h1(id, 50.0) < 0.5) ? 1.0 : 2.0;        // a speck's size
        vec2 q = floor(px / g);
        float v = h1(id, 51.0);
        vec3 col;
        if (v < 0.45) {                                     // snow: dark blue, bright specks of every colour
            vec2 t = q + vec2(tick * 17.0, tick * 31.0);
            vec3 n = vec3(hp(t, 52.0), hp(t, 53.0), hp(t, 54.0));
            col = step(vec3(0.8 + 0.12 * h1(id, 55.0)), n);
            if (col == vec3(0.0)) col = vec3(0.05, 0.08, 0.28) * (0.4 + 1.2 * n.x);
        } else if (v < 0.7) {                               // streaks: columns that repeat down the block
            float per = 1.0 + floor(h1(id, 56.0) * 6.0);
            float cx = floor(q.x / per);
            vec3 n = vec3(h1(cx + id, 57.0 + tick), h1(cx * 1.3 + id, 58.0 + tick), h1(cx * 2.1 + id, 59.0 + tick));
            float row = h1(floor(q.y / (1.0 + floor(h1(id, 60.0) * 4.0))) + id, 61.0 + tick);
            col = mix(step(vec3(0.5), n), vec3(row), 0.3 * step(0.7, row));
        } else {                                            // the picture dithered to a few bits, from elsewhere
            vec2 off = floor((vec2(h1(id, 62.0), h1(id, 63.0)) - 0.5) * 2.0 * 0.4 * resolution);
            vec2 p = mod(floor(px / (g * 3.0)) * (g * 3.0) + off, resolution);
            vec4 c = unpremultiply(src((p + 0.5) / resolution));
            vec2 t = q + vec2(tick * 17.0, tick * 31.0);
            vec3 n = vec3(hp(t, 64.0), hp(t, 65.0), hp(t, 66.0));
            col = step(n, c.rgb * c.rgb * 0.9);
            if (col == vec3(0.0)) col = vec3(0.04, 0.07, 0.25);
        }
        return vec4(col, 1.0);
    }

    // gone
    if (gone_look == 1) return vec4(0.0);
    if (gone_look == 2) return vec4(1.0);
    return vec4(0.0, 0.0, 0.0, 1.0);
}
