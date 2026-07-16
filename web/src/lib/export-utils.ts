import jsPDF from "jspdf";
import html2canvas from "html2canvas";
import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  HeadingLevel,
  AlignmentType,
  BorderStyle,
} from "docx";
import { saveAs } from "file-saver";

interface FaultAnalysisDetailForExport {
  fault_id?: string;
  id?: string;
  line_name: string;
  station?: string;
  fault_datetime?: string;
  fault_time?: string;
  fault_type?: string;
  confidence?: number;
  sections?: Array<{
    title: string;
    content: Array<{
      type: "text" | "subtitle" | "bullet" | "highlight" | "card";
      text: string;
      items?: string[];
    }>;
  }>;
}

/**
 * 导出为PDF - 使用HTML渲染方式
 */
export async function exportToPDF(
  detail: FaultAnalysisDetailForExport,
  elementId: string = "export-content"
) {
  const element = document.getElementById(elementId);
  if (!element) {
    throw new Error("未找到要导出的内容");
  }

  // 使用html2canvas将HTML转换为canvas
  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    logging: false,
    backgroundColor: "#ffffff",
    ignoreElements: (element) => {
      // 忽略某些可能导致问题的元素
      return element.classList?.contains('ant-dropdown') || false;
    },
    onclone: (clonedDoc) => {
      // 在克隆的文档中移除所有外部样式表，只保留内联样式
      const styleSheets = clonedDoc.styleSheets;
      for (let i = styleSheets.length - 1; i >= 0; i--) {
        try {
          const sheet = styleSheets[i];
          if (sheet.href || sheet.ownerNode?.nodeName === 'STYLE') {
            sheet.disabled = true;
          }
        } catch (e) {
          // 跨域样式表可能无法访问，忽略错误
        }
      }

      // 为导出元素添加基本样式
      const exportElement = clonedDoc.getElementById(elementId);
      if (exportElement) {
        exportElement.style.fontFamily = 'Arial, sans-serif';
        exportElement.style.fontSize = '14px';
        exportElement.style.lineHeight = '1.6';
        exportElement.style.color = '#333333';

        // 递归处理所有元素，添加必要的样式
        const processElement = (el: Element) => {
          if (el instanceof HTMLElement) {
            // 为标题添加样式
            if (el.tagName === 'H1' || el.tagName === 'H2' || el.tagName === 'H3') {
              el.style.fontWeight = 'bold';
              el.style.marginBottom = '16px';
            }

            // 处理包含主题色背景的元素（章节标题）
            const inlineStyle = el.getAttribute('style') || '';
            if (inlineStyle.includes('var(--ant-color-primary)') ||
                inlineStyle.includes('var(--accent-contrast)')) {
              el.style.backgroundColor = '#8b5cf6'; // 主题紫色
              el.style.color = '#ffffff';
              el.style.padding = '12px 20px';
              el.style.borderRadius = '6px';
              el.style.marginBottom = '16px';
              el.style.fontWeight = '600';
            }

            // 处理边框和阴影
            if (el.style.borderColor) {
              el.style.borderColor = '#e5e7eb';
            }
            if (el.style.boxShadow && el.style.boxShadow.includes('color-mix')) {
              el.style.boxShadow = 'none';
            }

            // 为列表项添加样式
            if (el.tagName === 'LI') {
              el.style.marginBottom = '8px';
            }

            // 为段落添加样式
            if (el.tagName === 'P') {
              el.style.marginBottom = '12px';
            }
          }

          // 递归处理子元素
          Array.from(el.children).forEach(processElement);
        };

        processElement(exportElement);
      }
    },
  });

  const imgData = canvas.toDataURL("image/png");
  const pdf = new jsPDF({
    orientation: "portrait",
    unit: "mm",
    format: "a4",
  });

  const imgWidth = 210; // A4宽度
  const pageHeight = 297; // A4高度
  const imgHeight = (canvas.height * imgWidth) / canvas.width;
  let heightLeft = imgHeight;
  let position = 0;

  // 添加第一页
  pdf.addImage(imgData, "PNG", 0, position, imgWidth, imgHeight);
  heightLeft -= pageHeight;

  // 如果内容超过一页，添加更多页
  while (heightLeft > 0) {
    position = heightLeft - imgHeight;
    pdf.addPage();
    pdf.addImage(imgData, "PNG", 0, position, imgWidth, imgHeight);
    heightLeft -= pageHeight;
  }

  pdf.save(`${detail.fault_id || detail.id || '故障分析'}_故障分析报告.pdf`);
}

/**
 * 导出为Word文档
 */
export async function exportToWord(detail: FaultAnalysisDetailForExport) {
  const children: Paragraph[] = [];

  const reportId = detail.fault_id || detail.id || '故障分析';
  const faultTime = detail.fault_datetime || detail.fault_time || '';

  // 标题
  children.push(
    new Paragraph({
      text: `${reportId} 故障分析报告`,
      heading: HeadingLevel.HEADING_1,
      alignment: AlignmentType.CENTER,
      spacing: { after: 300 },
    })
  );

  // 基本信息
  children.push(
    new Paragraph({
      children: [
        new TextRun({
          text: `线路: ${detail.line_name}`,
          size: 24,
        }),
      ],
      spacing: { after: 100 },
    })
  );

  if (detail.station) {
    children.push(
      new Paragraph({
        children: [
          new TextRun({
            text: `录波记录厂站: ${detail.station}`,
            size: 24,
          }),
        ],
        spacing: { after: 100 },
      })
    );
  }

  children.push(
    new Paragraph({
      children: [
        new TextRun({
          text: `故障时间: ${faultTime}`,
          size: 24,
        }),
      ],
      spacing: { after: 300 },
    })
  );

  if (detail.fault_type) {
    children.push(
      new Paragraph({
        children: [
          new TextRun({
            text: `故障类型: ${detail.fault_type}`,
            size: 24,
          }),
        ],
        spacing: { after: 100 },
      })
    );
  }

  if (detail.confidence) {
    children.push(
      new Paragraph({
        children: [
          new TextRun({
            text: `置信度: ${detail.confidence.toFixed(1)}%`,
            size: 24,
          }),
        ],
        spacing: { after: 300 },
      })
    );
  }

  // 内容章节
  detail.sections?.forEach((section) => {
    // 章节标题
    children.push(
      new Paragraph({
        text: section.title,
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 300, after: 200 },
      })
    );

    // 章节内容
    section.content.forEach((item) => {
      if (item.type === "subtitle") {
        children.push(
          new Paragraph({
            children: [
              new TextRun({
                text: item.text,
                bold: true,
                size: 24,
              }),
            ],
            spacing: { before: 200, after: 100 },
          })
        );
      } else if (item.type === "bullet" && item.items) {
        item.items.forEach((bullet) => {
          children.push(
            new Paragraph({
              text: bullet,
              bullet: { level: 0 },
              spacing: { after: 100 },
            })
          );
        });
      } else if (item.type === "highlight") {
        children.push(
          new Paragraph({
            children: [
              new TextRun({
                text: item.text,
                color: "F97316",
                bold: true,
                size: 24,
              }),
            ],
            spacing: { after: 150 },
          })
        );
      } else if (item.type === "card") {
        const lines = item.text.split("\n");
        lines.forEach((line, index) => {
          const isTitle = index === 0 || line === "决策建议";
          const isHighlight =
            line.includes("建议人工复核") || line.includes("雷击类型:");

          children.push(
            new Paragraph({
              children: [
                new TextRun({
                  text: line,
                  bold: isTitle,
                  color: isHighlight ? "F97316" : undefined,
                  size: 24,
                }),
              ],
              spacing: { after: 100 },
              indent: { left: 400 },
            })
          );
        });
        children.push(
          new Paragraph({
            text: "",
            spacing: { after: 200 },
          })
        );
      } else {
        // 普通文本
        children.push(
          new Paragraph({
            text: item.text,
            spacing: { after: 150 },
          })
        );
      }
    });
  });

  const doc = new Document({
    sections: [
      {
        properties: {},
        children: children,
      },
    ],
  });

  const blob = await Packer.toBlob(doc);
  saveAs(blob, `${reportId}_故障分析报告.docx`);
}
