# -*- coding: utf-8 -*-
"""
Created on Mon Aug 13 16:56:05 2018

@author: sunzz
"""

# -*- coding: utf-8 -*-
"""
Created on Sat Nov  4 16:00:16 2017
主要是删去work.atp中的变量替换部分，代替手工计算
@author: kakasun
"""

import os
pwd=os.getcwd()

# 修改ATPfile
def delete_some_string():
    # 找到起始位置
    atp_path=pwd+'\\work.atp'
    file_atp=open(atp_path)
    content = file_atp.read()
    pos = content.find( "$PARAMETER") # 15XXIAMP-1 get pointer position of special word
    pos_start = pos + 10
    file_atp.close()
    
    # 找到结束的位置
    file_atp=open(atp_path)
    content = file_atp.read()
    pos = content.find( "RER001=RER001I") # 15XXIAMP-1 get pointer position of special word
    pos_end = pos
    file_atp.close()

    content = content[:pos_start]  + '\n' + content[pos_end:]  
    file_atp2 = open(atp_path, "w" )  #  覆盖写入
    file_atp2.write( content )  
    file_atp2.close()
    
    return

"""
****************************************
主程序如下：
****************************************
"""
delete_some_string()
#os.system("pause")