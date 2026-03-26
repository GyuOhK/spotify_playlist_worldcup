import streamlit as st
import requests
import random
import copy
import json
import os
import re
import time
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

# --- 페이지 설정 ---
st.set_page_config(page_title="Spotify 이상형 월드컵", layout="wide", initial_sidebar_state="expanded")

# --- 스타일 커스텀 (CSS) ---
st.markdown("""
    <style>
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 5rem !important;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
    }
    .vs-text {
        text-align: center;
        font-size: 50px;
        font-weight: bold;
        color: #1DB954;
        margin-top: 10px;
    }
    .result-card {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 10px;
        margin-bottom: 5px;
        border-left: 5px solid #1DB954;
    }
    .like-card {
        background-color: #f0fff4;
        padding: 10px;
        border-radius: 10px;
        margin-bottom: 5px;
        border: 1px solid #1DB954;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- Spotify 설정 ---
SPOTIFY_SCOPES = "playlist-read-private"

def get_credentials():
    try:
        client_id = st.secrets["SPOTIFY_CLIENT_ID"]
        client_secret = st.secrets["SPOTIFY_CLIENT_SECRET"]
        redirect_uri = st.secrets["REDIRECT_URI"]
    except (KeyError, FileNotFoundError):
        client_id = os.environ.get('SPOTIFY_CLIENT_ID', '')
        client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET', '')
        redirect_uri = os.environ.get('REDIRECT_URI', 'http://localhost:8501')
    return client_id, client_secret, redirect_uri

def get_auth_url(client_id, redirect_uri):
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SPOTIFY_SCOPES,
        "show_dialog": "false",
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)

def exchange_code_for_token(code, client_id, client_secret, redirect_uri):
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
    )
    resp.raise_for_status()
    return resp.json()

def is_token_valid():
    return (
        "spotify_token" in st.session_state
        and time.time() < st.session_state.get("token_expires_at", 0)
    )

# --- OAuth 콜백 처리 ---
client_id, client_secret, redirect_uri = get_credentials()
query_params = st.query_params.to_dict()

if "code" in query_params and not is_token_valid():
    try:
        token_data = exchange_code_for_token(
            query_params["code"], client_id, client_secret, redirect_uri
        )
        st.session_state.spotify_token = token_data["access_token"]
        st.session_state.token_expires_at = time.time() + token_data.get("expires_in", 3600)
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Spotify 로그인 실패: {e}")
        st.query_params.clear()

# --- 상태 초기화 ---
if 'playlist_data' not in st.session_state: st.session_state.playlist_data = []
if 'current_round_list' not in st.session_state: st.session_state.current_round_list = []
if 'next_round_list' not in st.session_state: st.session_state.next_round_list = []
if 'game_started' not in st.session_state: st.session_state.game_started = False
if 'winner' not in st.session_state: st.session_state.winner = None
if 'current_pair' not in st.session_state: st.session_state.current_pair = []
if 'bye_video' not in st.session_state: st.session_state.bye_video = None
if 'match_history' not in st.session_state: st.session_state.match_history = []
if 'liked_videos' not in st.session_state: st.session_state.liked_videos = []
if 'history_stack' not in st.session_state: st.session_state.history_stack = []
if 'balloons_shown' not in st.session_state: st.session_state.balloons_shown = False

# --- 함수 정의 ---
def display_track(track_id):
    embed_html = f"""
    <iframe src="https://open.spotify.com/embed/track/{track_id}?utm_source=generator"
        width="100%" height="152" frameBorder="0"
        allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
        loading="lazy"></iframe>
    """
    st.markdown(embed_html, unsafe_allow_html=True)

def fetch_playlist(url):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    if not match:
        raise ValueError("올바른 Spotify 플레이리스트 URL이 아닙니다.\n예: https://open.spotify.com/playlist/...")
    playlist_id = match.group(1)

    headers = {"Authorization": f"Bearer {st.session_state.spotify_token}"}
    tracks = []
    next_url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit=50"
    while next_url:
        resp = requests.get(next_url, headers=headers)
        if resp.status_code == 401:
            # 토큰 만료 → 재로그인 유도
            del st.session_state["spotify_token"]
            st.session_state["token_expires_at"] = 0
            raise ValueError("Spotify 토큰이 만료되었습니다. 다시 로그인해주세요.")
        resp.raise_for_status()
        data = resp.json()
        for item in data.get('items', []):
            track = item.get('track')
            if not track or not track.get('id'):
                continue
            images = track['album'].get('images', [])
            tracks.append({
                'id': track['id'],
                'title': track['name'],
                'artist': ', '.join(a['name'] for a in track['artists']),
                'album': track['album']['name'],
                'image': images[0]['url'] if images else None,
                'url': track['external_urls']['spotify'],
            })
        next_url = data.get('next')
    return tracks

def reset_game():
    st.session_state.game_started = False
    st.session_state.winner = None
    st.session_state.playlist_data = []
    st.session_state.current_round_list = []
    st.session_state.next_round_list = []
    st.session_state.current_pair = []
    st.session_state.bye_video = None
    st.session_state.match_history = []
    st.session_state.liked_videos = []
    st.session_state.history_stack = []
    st.session_state.balloons_shown = False

def toggle_like(track):
    liked_ids = [v['id'] for v in st.session_state.liked_videos]
    if track['id'] in liked_ids:
        st.session_state.liked_videos = [v for v in st.session_state.liked_videos if v['id'] != track['id']]
    else:
        st.session_state.liked_videos.append(track)

def save_current_state():
    state_snapshot = {
        'current_round_list': copy.deepcopy(st.session_state.current_round_list),
        'next_round_list': copy.deepcopy(st.session_state.next_round_list),
        'current_pair': copy.deepcopy(st.session_state.current_pair),
        'bye_video': copy.deepcopy(st.session_state.bye_video),
        'match_history': copy.deepcopy(st.session_state.match_history),
        'winner': st.session_state.winner,
        'balloons_shown': st.session_state.balloons_shown,
    }
    st.session_state.history_stack.append(state_snapshot)

def undo_last_action():
    if st.session_state.history_stack:
        prev = st.session_state.history_stack.pop()
        st.session_state.current_round_list = prev['current_round_list']
        st.session_state.next_round_list = prev['next_round_list']
        st.session_state.current_pair = prev['current_pair']
        st.session_state.bye_video = prev['bye_video']
        st.session_state.match_history = prev['match_history']
        st.session_state.winner = prev['winner']
        st.session_state.balloons_shown = prev.get('balloons_shown', False)
        st.rerun()

def check_round_end():
    if not st.session_state.current_round_list and not st.session_state.current_pair and not st.session_state.bye_video:
        if len(st.session_state.next_round_list) == 1:
            st.session_state.winner = st.session_state.next_round_list[0]
        else:
            st.session_state.current_round_list = st.session_state.next_round_list
            st.session_state.next_round_list = []
            random.shuffle(st.session_state.current_round_list)

def select_winner(choice_idx):
    save_current_state()
    pair = st.session_state.current_pair
    winner = pair[choice_idx]
    loser = pair[1 - choice_idx]

    total = (len(st.session_state.next_round_list) * 2) + len(st.session_state.current_pair) + len(st.session_state.current_round_list)
    if st.session_state.bye_video: total += 1
    round_name = "결승전" if total <= 2 else f"{total}강"

    st.session_state.match_history.append({
        'round': round_name,
        'winner': winner['title'], 'winner_artist': winner['artist'],
        'loser': loser['title'], 'loser_artist': loser['artist'],
    })
    st.session_state.next_round_list.append(winner)
    st.session_state.current_pair = []
    check_round_end()
    st.rerun()

def confirm_bye():
    if st.session_state.bye_video:
        save_current_state()
        st.session_state.next_round_list.append(st.session_state.bye_video)
        st.session_state.bye_video = None
        check_round_end()
        st.rerun()

def find_track_by_title(title):
    for t in st.session_state.playlist_data:
        if t['title'] == title: return t
    return None

def get_game_state_json():
    data = {
        'playlist_data': st.session_state.playlist_data,
        'current_round_list': st.session_state.current_round_list,
        'next_round_list': st.session_state.next_round_list,
        'game_started': st.session_state.game_started,
        'winner': st.session_state.winner,
        'current_pair': st.session_state.current_pair,
        'bye_video': st.session_state.bye_video,
        'match_history': st.session_state.match_history,
        'liked_videos': st.session_state.liked_videos,
        'history_stack': st.session_state.history_stack,
        'balloons_shown': st.session_state.balloons_shown,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)

def load_game_state(uploaded_file):
    if uploaded_file is not None:
        try:
            data = json.load(uploaded_file)
            st.session_state.playlist_data = data.get('playlist_data', [])
            st.session_state.current_round_list = data.get('current_round_list', [])
            st.session_state.next_round_list = data.get('next_round_list', [])
            st.session_state.game_started = data.get('game_started', False)
            st.session_state.winner = data.get('winner', None)
            st.session_state.current_pair = data.get('current_pair', [])
            st.session_state.bye_video = data.get('bye_video', None)
            st.session_state.match_history = data.get('match_history', [])
            st.session_state.liked_videos = data.get('liked_videos', [])
            st.session_state.history_stack = data.get('history_stack', [])
            st.session_state.balloons_shown = data.get('balloons_shown', False)
            return True
        except Exception as e:
            st.error(f"파일 불러오기 실패: {e}")
            return False
    return False

# --- 사이드바 ---
with st.sidebar:
    st.header("💾 게임 데이터 관리")
    st.caption("게임 상태를 저장하거나 불러올 수 있습니다.")

    if st.session_state.game_started:
        json_str = get_game_state_json()
        st.download_button("📥 현재 상태 파일로 저장", json_str, "worldcup_save.json", "application/json")

    st.divider()
    uploaded_file = st.file_uploader("📤 저장된 파일 불러오기", type=['json'])
    if uploaded_file and st.button("파일 적용하여 이어하기"):
        if load_game_state(uploaded_file): st.success("게임을 불러왔습니다!"); st.rerun()

    if is_token_valid():
        st.divider()
        if st.button("🔓 Spotify 로그아웃"):
            del st.session_state["spotify_token"]
            st.session_state["token_expires_at"] = 0
            reset_game()
            st.rerun()

# --- 로그인 화면 ---
if not is_token_valid():
    st.title("🎵 Spotify 플레이리스트 이상형 월드컵")
    st.write("")
    st.write("Spotify 계정으로 로그인하면 플레이리스트를 가져올 수 있습니다.")
    st.write("")
    auth_url = get_auth_url(client_id, redirect_uri)
    st.link_button("🟢 Spotify로 로그인", auth_url, use_container_width=False)
    st.stop()

# --- 이하 로그인된 상태에서만 실행 ---

if not st.session_state.game_started:
    st.title("🎵 Spotify 플레이리스트 이상형 월드컵")
    st.write("")
    st.info("Spotify 플레이리스트 URL을 입력하세요.\n예: https://open.spotify.com/playlist/...")
    url = st.text_input("링크 입력", placeholder="https://open.spotify.com/playlist/...")
    st.write("")
    use_partial = st.checkbox("⚙️ 플레이리스트의 일부 곡만 가져오기")

    target_count = 16
    start_index = 1
    slice_method = "랜덤"

    if "slice_mode" not in st.session_state:
        st.session_state.slice_mode = "랜덤"

    if use_partial:
        if st.session_state.slice_mode == "특정 순서부터":
            cols = st.columns([2, 1, 1])
        else:
            cols = st.columns([1, 1])

        with cols[0]:
            target_count = st.number_input("가져올 곡 수", min_value=2, value=32, step=1)
        with cols[1]:
            slice_method = st.selectbox("가져올 방식", ["랜덤", "앞에서부터", "뒤에서부터", "특정 순서부터"], key="slice_mode")
        if slice_method == "특정 순서부터":
            with cols[2]:
                start_index = st.number_input("시작 번호", min_value=1, value=1, step=1)

    st.write("")
    if st.button("게임 시작하기", use_container_width=True):
        if url:
            with st.spinner("플레이리스트 목록을 가져오는 중..."):
                try:
                    tracks = fetch_playlist(url)

                    if use_partial and len(tracks) > target_count:
                        if slice_method == "앞에서부터":
                            tracks = tracks[:target_count]
                        elif slice_method == "뒤에서부터":
                            tracks = tracks[-target_count:]
                        elif slice_method == "랜덤":
                            tracks = random.sample(tracks, target_count)
                        elif slice_method == "특정 순서부터":
                            start_idx = max(0, start_index - 1)
                            tracks = tracks[start_idx:start_idx + target_count]

                    if len(tracks) < 2:
                        st.error(f"곡이 부족합니다. (추출된 곡: {len(tracks)}개)")
                    else:
                        random.shuffle(tracks)
                        st.session_state.playlist_data = tracks
                        st.session_state.current_round_list = tracks[:]
                        st.session_state.game_started = True
                        st.rerun()
                except Exception as e:
                    st.error(f"오류가 발생했습니다: {e}")
        else:
            st.warning("URL을 입력해주세요.")

elif st.session_state.winner:
    if not st.session_state.balloons_shown:
        st.balloons()
        st.session_state.balloons_shown = True

    st.title("👑 최종 우승! 👑")
    winner = st.session_state.winner

    reversed_history = list(reversed(st.session_state.match_history))
    unique_rounds = []
    for match in reversed_history:
        if match['round'] not in unique_rounds: unique_rounds.append(match['round'])

    st.write("#### 🎖️ 전체 순위")

    with st.expander(f"🏆 {winner['title']} — {winner['artist']}", expanded=True):
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            display_track(winner['id'])

    current_start_rank = 2
    for r_idx, r_name in enumerate(unique_rounds):
        losers_in_round = [find_track_by_title(m['loser']) for m in reversed_history if m['round'] == r_name]
        losers_in_round = [l for l in losers_in_round if l]

        count = len(losers_in_round)
        if count == 0: continue
        end_rank = current_start_rank + count - 1
        rank_str = f"{current_start_rank}위" if current_start_rank == end_rank else f"{current_start_rank}~{end_rank}위"

        if r_idx == 0: rank_title = "🥈 2위 (준우승)"
        elif r_idx == 1 and r_name == "4강": rank_title = "🥉 3~4위 (Top 4)"
        else:
            if r_idx == len(unique_rounds) - 1: rank_title = f"🏅 {rank_str} ({r_name})"
            else: rank_title = f"🏅 {rank_str} ({r_name} 진출)"

        st.markdown("---")
        st.caption(f"**{rank_title}**")
        for track in losers_in_round:
            with st.expander(f"{track['title']} — {track['artist']}"):
                c1, c2, c3 = st.columns([1, 2, 1])
                with c2:
                    display_track(track['id'])
        current_start_rank += count

    st.divider()
    if st.session_state.history_stack and st.button("↩️ 결과 취소하고 결승전으로 돌아가기"):
        undo_last_action()

    st.divider()
    st.subheader("❤️ 내가 찜한 곡들")
    if st.session_state.liked_videos:
        st.write("")
        cols = st.columns(3)
        for idx, track in enumerate(st.session_state.liked_videos):
            with cols[idx % 3]:
                st.markdown(
                    f"<div class='like-card'><b>{track['title']}</b><br>"
                    f"<small>{track['artist']}</small><br>"
                    f"<a href='{track['url']}' target='_blank'>Spotify에서 듣기</a></div>",
                    unsafe_allow_html=True
                )
    else:
        st.caption("아직 찜한 곡이 없습니다.")

    st.divider()
    st.subheader("📜 대진 기록")
    for match in reversed(st.session_state.match_history):
        winner_text = f"{match['winner']}"
        if match.get('winner_artist'): winner_text += f" <small>({match['winner_artist']})</small>"
        loser_text = f"{match['loser']}"
        if match.get('loser_artist'): loser_text += f" <small>({match['loser_artist']})</small>"
        st.markdown(
            f"<div class='result-card'><small>{match['round']}</small><br>"
            f"<span style='color:#1DB954; font-weight:bold;'>🏆 {winner_text}</span> vs "
            f"<span style='color:gray; text-decoration:line-through;'>{loser_text}</span></div>",
            unsafe_allow_html=True
        )

    if st.button("다시 하기"): reset_game(); st.rerun()

else:
    # --- 게임 진행 화면 ---
    if not st.session_state.current_pair and not st.session_state.bye_video:
        if len(st.session_state.current_round_list) >= 2:
            v1 = st.session_state.current_round_list.pop()
            v2 = st.session_state.current_round_list.pop()
            st.session_state.current_pair = [v1, v2]
        elif len(st.session_state.current_round_list) == 1:
            st.session_state.bye_video = st.session_state.current_round_list.pop()

    if st.session_state.bye_video:
        st.subheader("🎉 부전승")
        b_track = st.session_state.bye_video
        col_l, col_c, col_r = st.columns([2, 3, 2])
        with col_c:
            display_track(b_track['id'])
            st.markdown(f"<h3 style='text-align:center;'>{b_track['title']}</h3>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align:center; color:gray;'>{b_track['artist']}</p>", unsafe_allow_html=True)
            is_liked = b_track['id'] in [v['id'] for v in st.session_state.liked_videos]
            if st.button("❤️ 좋아요 취소" if is_liked else "🤍 좋아요", key=f"like_bye_{b_track['id']}", use_container_width=True):
                toggle_like(b_track); st.rerun()
            st.write("")
            if st.button("🚀 다음 라운드로 진출하기", type="primary", use_container_width=True):
                confirm_bye()
        st.divider()
        if st.session_state.history_stack:
            _, c_center, _ = st.columns([5, 2, 5])
            with c_center:
                if st.button("↩️ 무르기", use_container_width=True):
                    undo_last_action()

    elif st.session_state.current_pair:
        participants_in_next = len(st.session_state.next_round_list)
        participants_current = len(st.session_state.current_round_list) + len(st.session_state.current_pair)
        if st.session_state.bye_video: participants_current += 1
        total = (participants_in_next * 2) + participants_current
        total_matches = total // 2
        current_match_seq = participants_in_next + 1
        round_name = "결승전" if total <= 2 else f"{total}강"

        if round_name == "결승전":
            st.subheader(f"⚔️ {round_name}")
        else:
            st.subheader(f"⚔️ {round_name} ({current_match_seq}/{total_matches})")

        col1, col2, col3 = st.columns([1, 0.3, 1])
        pair = st.session_state.current_pair
        liked_ids = [v['id'] for v in st.session_state.liked_videos]

        with col1:
            display_track(pair[0]['id'])
            st.write(f"**{pair[0]['title']}**")
            st.caption(pair[0]['artist'])
            if st.button("❤️ 좋아요 취소" if pair[0]['id'] in liked_ids else "🤍 좋아요", key=f"like_{pair[0]['id']}"):
                toggle_like(pair[0]); st.rerun()
            if st.button("👈 이 곡 선택", key="btn_select_1", type="primary"):
                select_winner(0)

        with col2:
            for _ in range(7):
                st.write("")

            if st.button("🎲 리롤", key="reroll_btn", use_container_width=True, help="남은 대진을 다시 섞습니다"):
                pool = st.session_state.current_round_list + st.session_state.current_pair
                random.shuffle(pool)
                st.session_state.current_round_list = pool
                if len(st.session_state.current_round_list) >= 2:
                    v1 = st.session_state.current_round_list.pop()
                    v2 = st.session_state.current_round_list.pop()
                    st.session_state.current_pair = [v1, v2]
                st.rerun()

            st.markdown('<div class="vs-text">VS</div>', unsafe_allow_html=True)
            st.write("")
            st.write("")

            if st.session_state.history_stack:
                if st.button("↩️ 무르기", key="undo_match", use_container_width=True):
                    undo_last_action()

        with col3:
            display_track(pair[1]['id'])
            st.write(f"**{pair[1]['title']}**")
            st.caption(pair[1]['artist'])
            if st.button("❤️ 좋아요 취소" if pair[1]['id'] in liked_ids else "🤍 좋아요", key=f"like_{pair[1]['id']}"):
                toggle_like(pair[1]); st.rerun()
            if st.button("이 곡 선택 👉", key="btn_select_2", type="primary"):
                select_winner(1)
