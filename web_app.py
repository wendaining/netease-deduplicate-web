import streamlit as st
import pandas as pd
import main  # 调用后端逻辑
import time

# ==========================================
#  UI 配置与工具
# ==========================================
st.set_page_config(
    page_title="网易云歌单集成工具", 
    page_icon="🎵", 
    layout="wide",
    initial_sidebar_state="expanded"
)

@st.cache_data(ttl=3600)
def cached_fetch(pid):
    """包装 main.py 的爬虫逻辑，增加 Streamlit 缓存"""
    return main.logic_crawler(pid)

def to_csv(df):
    return df.to_csv(index=False, encoding='utf_8_sig').encode('utf_8_sig')

# ==========================================
#  侧边栏：导航与说明
# ==========================================
with st.sidebar:
    st.title("🎛️ 功能控制台")
    
    app_mode = st.radio("请选择操作模式", [
        "🧹 单歌单内部查重", 
        "🤝 双歌单求交集", 
        "➖ 双歌单求差集", 
        "➕ 双歌单求并集"
    ])
    
    st.markdown("---")
    
    with st.expander("📖 关于匹配模式", expanded=True):
        st.markdown("""
        **🔓 模糊模式 (推荐)**
        * 智能清洗歌名，忽略 `(Live)`、`Remix`、`（中文版）` 等后缀。
        * 忽略大小写差异。
        * **适合场景**：寻找两人共同喜好、合并重复歌单。
        
        **🔒 严格模式**
        * 仅匹配 `歌曲ID`。
        * 必须是完全同一个音频文件才算相同。
        * **适合场景**：精确的数据备份、迁移。
        """)
        
    st.caption("Core logic powered by `pyncm` & `pandas`")

# ==========================================
#  主界面
# ==========================================
st.title("🎵 网易云歌单集成工具 (Web版)")

# ==========================================
#  功能 1: 内部查重
# ==========================================
if app_mode == "🧹 单歌单内部查重":
    st.header("🧹 单歌单内部查重")
    st.markdown("""
    > **功能说明**：帮你找出歌单里那些 **“看似不同、实则重复”** 的歌曲（例如同时收藏了录音室版和演唱会版）。
    """)
    
    col1, col2 = st.columns([3, 1])
    with col1:
        url = st.text_input("请输入歌单链接或 ID 👇", placeholder="例如: https://music.163.com/playlist?id=...")
    with col2:
        st.write("") # 占位
        st.write("") 
        start_btn = st.button("开始分析", type="primary", use_container_width=True)
    
    if start_btn:
        pid = main.parse_id(url)
        if not pid: st.error("❌ 无效 ID，请检查链接")
        else:
            with st.spinner("🚀 正在极速下载歌单数据..."):
                name, df, err = cached_fetch(pid)
            
            if err: st.error(err)
            else:
                st.success(f"✅ 已加载: **《{name}》** (共 {len(df)} 首)")
                
                # 调用后端
                result = main.logic_internal_check(df)
                
                if result.empty:
                    st.balloons()
                    st.info("🎉 太棒了！你的歌单非常干净，没有发现重复歌曲。")
                else:
                    st.warning(f"⚠️ 发现 **{result['匹配基准'].nunique()}** 组疑似重复歌曲：")
                    st.dataframe(
                        result, 
                        use_container_width=True, 
                        hide_index=True,
                        column_config={
                            "匹配基准": st.column_config.TextColumn("判定基准 (清洗后)", help="系统认为这些歌是同一首"),
                            "title": "歌名",
                            "artist": "歌手",
                            "album": "专辑"
                        }
                    )

# ==========================================
#  功能 2: 双歌单交集
# ==========================================
elif app_mode == "🤝 双歌单求交集":
    st.header("🤝 双歌单求交集 (A ∩ B)")
    st.markdown("""
    > **功能说明**：找出两个歌单中 **共同拥有的歌曲**。
    > * 适合寻找两个人的共同品味，或者查看新歌单里有多少旧歌。
    """)
    
    c1, c2 = st.columns(2)
    with c1: u1 = st.text_input("歌单 A (主):")
    with c2: u2 = st.text_input("歌单 B (副):")
    
    mode = st.radio("匹配标准", ["模糊模式 (推荐)", "严格模式"], horizontal=True)
    
    if st.button("开始比对", type="primary"):
        p1, p2 = main.parse_id(u1), main.parse_id(u2)
        if p1 and p2:
            with st.spinner("📥 正在下载两个歌单的数据..."):
                n1, d1, e1 = cached_fetch(p1)
                n2, d2, e2 = cached_fetch(p2)
            
            if e1 or e2: st.error(f"加载失败: {e1} {e2}")
            else:
                st.success(f"就绪: A **《{n1}》** vs B **《{n2}》**")
                
                if "模糊" in mode:
                    res_df, count = main.logic_fuzzy_intersection(n1, d1, n2, d2)
                    
                    if count == 0:
                        st.info("🤔 没有发现任何相似歌曲。")
                    else:
                        st.success(f"🎯 发现 **{count}** 组重合歌曲！")
                        st.dataframe(
                            res_df[['匹配基准', 'source', 'title', 'artist', 'album']], 
                            use_container_width=True, 
                            hide_index=True,
                            column_config={
                                "source": st.column_config.TextColumn("来源", help="[均有]表示完全一致，[A]/[B]表示版本不同"),
                            }
                        )
                else:
                    res_df = main.logic_strict_intersection([d1, d2])
                    st.info(f"🔢 ID 完全相同的歌曲: **{len(res_df)}** 首")
                    if not res_df.empty:
                        st.dataframe(res_df, use_container_width=True)
                
                if not res_df.empty:
                    st.download_button("📥 下载交集结果 CSV", to_csv(res_df), "intersection.csv")

# ==========================================
#  功能 3: 差集
# ==========================================
elif app_mode == "➖ 双歌单求差集":
    st.header("➖ 双歌单求差集 (A - B)")
    st.markdown("""
    > **功能说明**：找出 **在 A 中存在，但在 B 中不存在** 的歌曲。
    > * 适合场景：把“新歌单”里“旧歌单”已有的歌剔除，只保留没听过的新歌。
    """)
    
    c1, c2 = st.columns(2)
    with c1: u1 = st.text_input("歌单 A (保留):")
    with c2: u2 = st.text_input("歌单 B (剔除):")
    fuzzy = st.checkbox("启用模糊匹配?", value=True, help="勾选后，'晴天' 和 '晴天(Live)' 会被视为同一首而被剔除。")
    
    if st.button("计算差集", type="primary"):
        p1, p2 = main.parse_id(u1), main.parse_id(u2)
        if p1 and p2:
            n1, d1, _ = cached_fetch(p1)
            n2, d2, _ = cached_fetch(p2)
            
            m = 'fuzzy' if fuzzy else 'strict'
            res = main.logic_difference(d1, d2, mode=m)
            
            st.success(f"💎 A 中独有的歌曲: **{len(res)}** 首")
            st.dataframe(res[['title', 'artist', 'album']], use_container_width=True, hide_index=True)
            st.download_button("📥 下载差集 CSV", to_csv(res), "difference.csv")

# ==========================================
#  功能 4: 并集
# ==========================================
elif app_mode == "➕ 双歌单求并集":
    st.header("➕ 双歌单求并集 (A ∪ B)")
    st.markdown("""
    > **功能说明**：将两个歌单 **合并在一起**，并自动去除重复项。
    > * 适合场景：将多个小歌单整合成一个大歌单。
    """)
    
    c1, c2 = st.columns(2)
    with c1: u1 = st.text_input("歌单 A:")
    with c2: u2 = st.text_input("歌单 B:")
    fuzzy = st.checkbox("模糊去重?", value=True, help="勾选后，同名不同版本的歌只保留一首。")
    
    if st.button("合并去重", type="primary"):
        p1, p2 = main.parse_id(u1), main.parse_id(u2)
        if p1 and p2:
            n1, d1, _ = cached_fetch(p1)
            n2, d2, _ = cached_fetch(p2)
            
            m = 'fuzzy' if fuzzy else 'strict'
            res = main.logic_union([d1, d2], mode=m)
            
            st.success(f"📦 合并后总数: **{len(res)}** 首 (原总数: {len(d1)+len(d2)})")
            st.dataframe(res[['title', 'artist', 'album']], use_container_width=True, hide_index=True)
            st.download_button("📥 下载并集 CSV", to_csv(res), "union.csv")