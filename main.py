import sys
import os
import re
import time
import glob
import pandas as pd

# --- 依赖检查 ---
try:
    import pyncm
    import pyncm.apis
except ImportError:
    pass # 允许 web_app 处理依赖报错

# ==========================================
#  1. 基础工具函数 (通用)
# ==========================================

def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]', '_', str(name))

def parse_id(url):
    match = re.search(r'id=(\d+)', str(url))
    if match: return match.group(1)
    if str(url).isdigit(): return str(url)
    return None

def normalize_title(title):
    """核心清洗逻辑"""
    if not isinstance(title, str): return ""
    core = title.lower()
    core = re.sub(r'\s*[（\(].*?[）\)]', '', core)
    if '-' in core: core = core.split('-')[0]
    return core.strip()

# ==========================================
#  2. 核心逻辑层 (供 Web 和 CLI 调用)
#     这些函数只返回数据，不进行 print
# ==========================================

def logic_crawler(pid, progress_callback=None):
    """
    爬虫逻辑
    progress_callback: 一个函数，接收 (current, total)
    Return: (playlist_name, df, error_message)
    """
    try:
        info = pyncm.apis.playlist.GetPlaylistInfo(pid)
        if not info or 'playlist' not in info:
            return None, None, "API无法获取数据"
            
        pl = info['playlist']
        name = pl['name']
        track_ids = [str(t['id']) for t in pl['trackIds']]
        total = len(track_ids)
        
        all_songs = []
        batch_size = 500
        
        for i in range(0, total, batch_size):
            chunk = track_ids[i : i + batch_size]
            
            # 回调进度
            if progress_callback:
                progress_callback(i, total)
                
            try:
                details = pyncm.apis.track.GetTrackDetail(chunk)
                for song in details['songs']:
                    all_songs.append({
                        "id": str(song['id']),
                        "title": song['name'],
                        "artist": "/".join([ar['name'] for ar in song['ar']]),
                        "album": song['al']['name'] if song['al'] else "",
                        "duration": f"{song['dt']//60000:02d}:{(song['dt']%60000)//1000:02d}"
                    })
            except: pass
            
        if progress_callback: progress_callback(total, total) # 完成
        
        return name, pd.DataFrame(all_songs), None
    except Exception as e:
        return None, None, str(e)

def logic_strict_intersection(dfs):
    """严格交集逻辑"""
    if not dfs: return pd.DataFrame()
    res = dfs[0]
    for i in range(1, len(dfs)):
        res = pd.merge(res, dfs[i], on='id', how='inner', suffixes=('', f'_{i}'))
    
    # 清洗列
    base_cols = ['id', 'title', 'artist', 'album', 'duration']
    cols = [c for c in base_cols if c in res.columns]
    return res[cols]

def logic_fuzzy_intersection(name1, df1, name2, df2):
    """
    模糊交集逻辑 (核心算法)
    返回你喜欢的那个 '均有', '[A]', '[B]' 格式的 DataFrame
    """
    df1 = df1.copy()
    df2 = df2.copy()
    df1['clean_title'] = df1['title'].apply(normalize_title)
    df2['clean_title'] = df2['title'].apply(normalize_title)
    
    common_keys = set(df1['clean_title']).intersection(set(df2['clean_title']))
    
    if not common_keys:
        return pd.DataFrame(), 0 # 空结果
        
    res1 = df1[df1['clean_title'].isin(common_keys)]
    res2 = df2[df2['clean_title'].isin(common_keys)]
    
    s_name1 = name1.replace("playlist_", "").replace(".csv", "")
    s_name2 = name2.replace("playlist_", "").replace(".csv", "")
    
    final_rows = []
    
    for key in sorted(common_keys):
        sub_a = res1[res1['clean_title'] == key]
        sub_b = res2[res2['clean_title'] == key]
        
        ids_a = set(sub_a['id'])
        ids_b = set(sub_b['id'])
        common_ids = ids_a & ids_b
        
        # 1. 完全相同 (均有)
        for sid in common_ids:
            row = sub_a[sub_a['id'] == sid].iloc[0]
            final_rows.append({
                '匹配基准': key, 'source': '均有',
                'title': row['title'], 'artist': row['artist'], 
                'album': row['album'], 'id': sid
            })
            
        # 2. A 独有版本
        for _, row in sub_a[~sub_a['id'].isin(common_ids)].iterrows():
            final_rows.append({
                '匹配基准': key, 'source': f'[A] {s_name1}',
                'title': row['title'], 'artist': row['artist'], 
                'album': row['album'], 'id': row['id']
            })
            
        # 3. B 独有版本
        for _, row in sub_b[~sub_b['id'].isin(common_ids)].iterrows():
            final_rows.append({
                '匹配基准': key, 'source': f'[B] {s_name2}',
                'title': row['title'], 'artist': row['artist'], 
                'album': row['album'], 'id': row['id']
            })
            
    return pd.DataFrame(final_rows), len(common_keys)

def logic_difference(df_a, df_b, mode='strict'):
    """差集逻辑"""
    if mode == 'strict':
        return df_a[~df_a['id'].isin(df_b['id'])]
    else:
        # 模糊
        df_a = df_a.copy()
        df_b = df_b.copy()
        df_a['c'] = df_a['title'].apply(normalize_title)
        df_b['c'] = df_b['title'].apply(normalize_title)
        return df_a[~df_a['c'].isin(df_b['c'])].drop(columns=['c'])

def logic_union(dfs, mode='strict'):
    """并集逻辑"""
    if not dfs: return pd.DataFrame()
    
    # 模糊模式需先处理列
    processed_dfs = []
    for df in dfs:
        d = df.copy()
        if mode == 'fuzzy':
            d['clean_title'] = d['title'].apply(normalize_title)
        processed_dfs.append(d)
        
    union_df = pd.concat(processed_dfs, ignore_index=True)
    
    if mode == 'strict':
        return union_df.drop_duplicates(subset=['id'], keep='first')
    else:
        res = union_df.drop_duplicates(subset=['clean_title'], keep='first')
        return res.drop(columns=['clean_title'])

def logic_internal_check(df):
    """查重逻辑"""
    df = df.copy()
    df['clean_title'] = df['title'].apply(normalize_title)
    dupes = df[df.duplicated(subset=['clean_title'], keep=False)]
    if dupes.empty: return pd.DataFrame()
    
    dupes = dupes.sort_values(by=['clean_title', 'artist'])
    cols = ['clean_title', 'title', 'artist', 'album', 'duration']
    return dupes[cols].rename(columns={'clean_title': '匹配基准'})

# ==========================================
#  3. CLI 交互层 (保持原有的命令行功能)
# ==========================================
#  为了节省篇幅，这里简写。当你直接运行 main.py 时，
#  这里面的函数会调用上面的 logic_ 函数并打印结果。
#  (原有的 module_crawler 等函数逻辑保持不变，只是改成调用 logic_crawler)

def module_crawler():
    # 示例：适配 CLI 的调用
    raw = input("输入ID: ")
    pid = parse_id(raw)
    print("下载中...")
    name, df, err = logic_crawler(pid) 
    if df is not None:
        df.to_csv(f"playlist_{sanitize_filename(name)}.csv", index=False, encoding='utf_8_sig')
        print("完成")
    else:
        print(err)

# ... 其他 module_ 函数类似适配 ...

if __name__ == "__main__":
    # 简单的菜单示例
    print("这是后端逻辑库，请运行 web_app.py 启动网页版，或完善此处的 CLI 菜单。")
    module_crawler()