import os
os.environ["FONTCONFIG_PATH"] = "/etc/fonts"

!apt-get install poppler-utils
!apt-get install poppler-data
!pip install pdf2image
from google.colab import drive
drive.mount('/content/drive')
import os
import glob
import shutil
from tqdm import tqdm
import datetime

import cv2
import numpy as np
from PIL import Image

from pdf2image import convert_from_path

from gspread_dataframe import set_with_dataframe
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import json

import shutil

import datetime
import pytz

#日付を取得
dt_now_utc = datetime.datetime.now(pytz.utc)

# 日本のタイムゾーンを設定
jst = pytz.timezone('Asia/Tokyo')

# 日本時間に変換
dt_now = dt_now_utc.astimezone(jst)
dt_now = dt_now - datetime.timedelta(days=1)
date = str(dt_now.year) + "-" + dt_now.strftime("%m") + "-" + dt_now.strftime("%d")

base_path = '/content/drive/MyDrive/0_個人別基礎定着演習/06.リリース後修正/日付フォルダ格納/2025-08-02/問題png'
input_path = '/content/drive/MyDrive/0_個人別基礎定着演習/06.リリース後修正/日付フォルダ格納/2025-08-02/問題'
config_path = '/content/drive/MyDrive/0_個人別基礎定着演習/06.リリース後修正/png化/config.csv'

class QPngCreator:
    """
    Qpdfをpngに変換するためのクラス
    cv2の日本語対策はcenter_toolsのopencv_winからコピペ
    """
    def __init__(self, resize_flg,output_path=None, logpath=None):
        self.BASE_PATH = base_path
        self.TEMP_PATH = os.path.join(self.BASE_PATH, 'temp')
        self.resize_flg = resize_flg
        if output_path:
            self.output_path = output_path
        else:
            print_time = datetime.datetime.now().strftime('%y%m%d_%H%M%S')
            self.output_path = self.BASE_PATH
        if not os.path.isdir(self.output_path):
            os.makedirs(self.output_path)
        if logpath:
            self.logpath = logpath
        else:
            self.logpath = os.path.join(self.output_path, 'log.csv')
        # png仕様による最大サイズ
        self.SIZE_MAX = 65535

        # pdf2imageの設定
        # popplerのパスを通す
        poppler_dir = os.path.join(self.BASE_PATH, 'poppler', 'bin')
        os.environ['PATH'] += os.pathsep + os.path.join(poppler_dir)
        # dpi設定
        self.dpi = 350
        # 入力サイズ指定 tate:yoko
        # self.PAGE_SIZE = (640,)
        # 出力サイズ
        # csvから読み込み
        with open(config_path, encoding='shift_jis') as f:
            self.V_WIDTH = int(f.readline().split(',')[1])
            self.H_WIDTH = int(f.readline().split(',')[1])
        self.output_width = self.V_WIDTH
        # とりあえず作成するたかさ(SIZE_MAXをオーバーすると圧縮される)
        self.TEMP_HEIGHT = 100000
        self.pdf_path = None
        self.png_list = []

    def _write_log(self, target, message):
        """ログを記入する関数"""
        with open(self.logpath, mode='a', encoding='shift_jis') as f:
            f.write(target + ',' + message + '\n')

    def _cv2_read(self, filename, flags=cv2.IMREAD_COLOR, dtype=np.uint8):
        """cv2の読み込み日本語でも可能"""
        n = np.fromfile(filename, dtype)
        img = cv2.imdecode(n, flags)
        return img

    def _create_png(self):
        """pdfをpngに落とす"""
        if os.path.isdir(self.TEMP_PATH):
            shutil.rmtree(self.TEMP_PATH)
        os.makedirs(self.TEMP_PATH)

        pages = convert_from_path(self.pdf_path, dpi=self.dpi, fmt='png', thread_count=4)

        self.png_list = []
        for i, page in enumerate(pages):
            filepath = os.path.join(self.TEMP_PATH, '_{:02d}.png'.format(i+1))
            self.png_list.append(filepath)
            page.save(filepath, 'PNG')
            # 余白をカット
            if self.resize_flg:
                page = Image.open(filepath)
                width, height = page.size
                # クロッピング範囲を調整
                left = 250
                top = 350
                right = width - 250
                bottom = height - 350

                page_crop = page.crop((left, top, right, bottom))
                page_crop.save(filepath)

        self.png_list = sorted(self.png_list)
        return self.png_list

    def _set_output_width(self, png_path):
        """
        横幅の出力設定を行う
        縦長:640px, 横長:1000px
        """
        h, w, _ = self._cv2_read(png_path).shape
        if h >= w:
            self.output_width = self.V_WIDTH
        else:
            self.output_width = self.H_WIDTH

    def _create_board(self):
        """ベースとなる白紙を作る"""
        self.base_img = np.zeros((self.TEMP_HEIGHT, self.output_width,3), np.uint8)
        self.base_img.fill(255)
        # cv2.rectangle(self.base_img, (0, 0), (self.height, self.width), 255, -1)
        # cvio.win_write('base.png', self.base_img)
        return self.base_img

    def _paste_image(self, png_path):
        """画像を貼り付けていく関数"""
        page_img = self._cv2_read(png_path)
        scaling_rate = self.output_width / page_img.shape[1]
        new_size = (self.output_width, round(page_img.shape[0] * scaling_rate))
        page_img = cv2.resize(page_img, new_size, interpolation=cv2.INTER_AREA)

        if self.pasted_line + new_size[1] > self.TEMP_HEIGHT:
            return False
        self.base_img[self.pasted_line:self.pasted_line+new_size[1], :, :] = page_img
        self.pasted_line += new_size[1]
        return True

    def _save_png(self):
        """pngとして保存する関数"""
        if not os.path.isdir(self.output_path):
            os.makedirs(self.output_path)

        filepath = os.path.join(self.output_path, self.save_name + '.png')
        img_rgba = cv2.cvtColor(self.base_img, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(img_rgba)
        img_pil.save(filepath, dpi=(self.dpi, self.dpi))

    def resize_image(self):
        """サイズオーバーした画像をギリギリ入るまで縮小する関数"""
        if self.base_img.shape[0] < self.SIZE_MAX:
            return self.base_img
        scaling_rate = self.SIZE_MAX / self.base_img.shape[0]
        new_size = (round(self.base_img.shape[1] * scaling_rate), self.SIZE_MAX)
        self.base_img = cv2.resize(self.base_img, new_size, interpolation=cv2.INTER_AREA)
        return self.base_img

    def execute(self, pdf_path=None,png_list=None, save_name=None):
        """実行関数"""
        if pdf_path:  # PDFを用意した場合
            self.save_name = os.path.basename(pdf_path)[:-4]
            self.pdf_path = pdf_path
            self.png_list = self._create_png()
            target_name = os.path.basename(self.pdf_path)[:-4]
        elif png_list and save_name:  # PNGを用意した場合
            self.save_name = save_name
            self.pdf_path = None
            self.png_list = png_list
            target_name = save_name
        else:
            return False

        # もろもろの初期化
        self.pasted_line = 10
        self._set_output_width(self.png_list[0])
        # 白紙を作成
        self._create_board()

        over_flg = False
        for page_num, png_path in enumerate(self.png_list):
            if self.pasted_line >= self.SIZE_MAX and not over_flg:
                print(f'WARNING on {os.path.basename(png_path)}: {page_num+1}ページ目でサイズオーバーしたため、リサイズされます。')
                over_flg = True
            result = self._paste_image(png_path)
            if not result:
                print(f'ERROR on {os.path.basename(png_path)}: 処理できるサイズをオーバーしたため、このファイルのpng化を中止します。詳しくは開発者に問い合わせてください。')
                self._write_log(target_name, '処理可能サイズ超過')
                break

        self.base_img = self.base_img[:self.pasted_line, :]
        # print(self.base_img.shape)
        if over_flg:
            self.resize_image()
            self._write_log(target_name, 'リサイズ処理済')
        else:
            self._write_log(target_name, '正常')
        self._save_png()
        # tempフォルダ削除
        if self.pdf_path:
            shutil.rmtree(self.TEMP_PATH)
        return True



#定石問題演習の時はTrueにする　高等学校対応コースはFalse
resize_flg = False
QPC = QPngCreator(resize_flg)
# inputがない場合は終了
if not os.path.isdir(input_path):
    pass

pdf_list = [x for x in glob.glob(os.path.join(input_path, '*.pdf')) if os.path.isfile(x)]

all_cnt = len(pdf_list)
for i, pdf_path in enumerate(tqdm(pdf_list)):
    # print(f"{i+1}/{all_cnt}: {os.path.basename(pdf_path)}を処理中...")
    QPC.execute(pdf_path=pdf_path)

