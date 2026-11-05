// @filter 裁切
// @category 變換
// @description 節點用：照 Blender 的「裁切」（Crop）：留下 X、Y（從左下角算起）開始、寬 × 高的那一塊，外面是透明的。勾「透明度裁切」時留在原位；沒勾時 Blender 的圖會縮成裁出來的大小，這裡畫布大小不變，所以裁出來的那塊放在畫面中央（最後看到的和 Blender 一樣）
// @param x int 0 0 100000 "X"
// @param y int 0 0 100000 "Y"
// @param width int 1920 0 100000 "寬"
// @param height int 1080 0 100000 "高"
// @param alpha_crop bool false "透明度裁切"

// Reimplementation of Blender's Crop compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// The region is kept inside the picture and is at least a pixel wide and high; the picture the node gives is the region alone (Alpha Crop off: the canvas shrinks to
// it, so it sits in the middle of the canvas here) or the picture with everything outside the region transparent (Alpha Crop on).
vec4 effect(vec2 uv) {
    vec2 res = resolution;
    vec2 p = vec2(uv.x * res.x, (1.0 - uv.y) * res.y);                  // (pixels, Y up)
    vec2 lo = clamp(vec2(float(x), float(y)), vec2(0.0), res - 1.0);
    vec2 size = clamp(vec2(float(width), float(height)), vec2(1.0), res - lo);       // (at least one pixel, as Blender's)
    if (alpha_crop)
        return all(greaterThanEqual(p, lo)) && all(lessThan(p, lo + size)) ? src(uv) : vec4(0.0);
    vec2 off = floor((res - size) * 0.5);
    if (any(lessThan(p, off)) || any(greaterThanEqual(p, off + size))) return vec4(0.0);
    vec2 q = p - off + lo;
    return src(vec2(q.x / res.x, 1.0 - q.y / res.y));
}
