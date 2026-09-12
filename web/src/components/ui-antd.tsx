"use client";

import {
  Children,
  Fragment,
  cloneElement,
  createContext,
  isValidElement,
  useContext,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type ReactElement,
  type ReactNode,
  type TableHTMLAttributes,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from "react";
import {
  Alert,
  Button as AntButton,
  Card as AntCard,
  Checkbox as AntCheckbox,
  Dropdown as AntDropdown,
  Input,
  Modal as AntModal,
  Select as AntSelect,
  Typography,
  type CardProps as AntCardProps,
  type MenuProps,
} from "antd";

export {
  THEME_ACCENT_OPTIONS,
  THEME_MODE_OPTIONS,
  Theme,
  useThemeAppearance,
} from "./ui-theme";
export type { ThemeAccentColor, ThemeMode, ThemePrimaryMode } from "./ui-theme";
import {
  cn,
  isNativeButtonType,
  isVisualButtonType,
  mapButtonSize,
  mapHeadingLevel,
  mapInputSize,
  mapTextSize,
  toSpacingValue,
  withSpacingStyle,
} from "./ui-theme";
import type {
  ButtonProps,
  VisualButtonType,
} from "./ui-theme";

export function Button({
  asChild = false,
  color,
  variant,
  size,
  type: typeProp,
  htmlType,
  className,
  children,
  mt,
  mb,
  style,
  onClick,
  disabled,
  ...rest
}: ButtonProps) {
  const mappedSize = mapButtonSize(size);
  const danger = color === "red";
  const defaultVisualType: VisualButtonType =
    variant === "solid" && color !== "gray" ? "primary" : "default";
  const nativeType = isNativeButtonType(typeProp) ? typeProp : undefined;
  let visualType: VisualButtonType = defaultVisualType;
  if (isVisualButtonType(typeProp)) {
    visualType = typeProp;
  }
  const ghost = variant === "ghost";

  if (asChild && isValidElement(children)) {
    const child = Children.only(children) as ReactElement<{
      className?: string;
      onClick?: (event: unknown) => void;
    }>;
    const childClassName = cn(
      "ant-btn",
      visualType === "primary" ? "ant-btn-primary" : "ant-btn-default",
      mappedSize === "small" ? "ant-btn-sm" : "",
      mappedSize === "large" ? "ant-btn-lg" : "",
      danger ? "ant-btn-dangerous" : "",
      ghost ? "ant-btn-background-ghost" : "",
      disabled ? "ant-btn-disabled" : "",
      className,
      child.props.className,
    );
    return cloneElement(child, {
      className: childClassName,
      onClick: (event: unknown) => {
        child.props.onClick?.(event);
        if (!disabled) {
          (onClick as ((evt: unknown) => void) | undefined)?.(event);
        }
      },
    });
  }

  return (
    <AntButton
      {...rest}
      className={className}
      danger={danger}
      disabled={disabled}
      ghost={ghost}
      onClick={onClick}
      size={mappedSize}
      style={withSpacingStyle({ mt, mb, style })}
      htmlType={nativeType ?? htmlType}
      type={visualType}
    >
      {children}
    </AntButton>
  );
}

type TextProps = {
  children?: ReactNode;
  className?: string;
  color?: "gray" | string;
  size?: "1" | "2" | "3" | "4" | "5" | string;
  weight?: "light" | "regular" | "medium" | "bold" | string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

function mapWeight(weight?: string): CSSProperties["fontWeight"] {
  if (!weight) return undefined;
  if (weight === "light") return 300;
  if (weight === "regular") return 400;
  if (weight === "medium") return 500;
  if (weight === "bold") return 700;
  return weight as CSSProperties["fontWeight"];
}

export function Text({
  children,
  className,
  color,
  size,
  weight,
  mt,
  mb,
  style,
}: TextProps) {
  return (
    <Typography.Text
      className={className}
      style={{
        fontSize: mapTextSize(size),
        fontWeight: mapWeight(weight),
        ...withSpacingStyle({ mt, mb, style }),
      }}
      type={color === "gray" ? "secondary" : undefined}
    >
      {children}
    </Typography.Text>
  );
}

type HeadingProps = {
  children?: ReactNode;
  className?: string;
  as?: "h1" | "h2" | "h3" | "h4" | "h5";
  size?: string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

export function Heading({
  children,
  className,
  as,
  size,
  mt,
  mb,
  style,
}: HeadingProps) {
  return (
    <Typography.Title
      className={className}
      level={mapHeadingLevel(size, as)}
      style={{
        margin: 0,
        ...withSpacingStyle({ mt, mb, style }),
      }}
    >
      {children}
    </Typography.Title>
  );
}

type FlexProps = {
  children?: ReactNode;
  className?: string;
  direction?: "row" | "column";
  gap?: string | number;
  align?: "start" | "center" | "end" | "baseline" | "stretch";
  justify?:
    | "start"
    | "center"
    | "end"
    | "between"
    | "around"
    | "evenly";
  wrap?: "wrap" | "nowrap" | boolean;
  height?: string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

function mapAlign(align?: FlexProps["align"]): CSSProperties["alignItems"] {
  if (align === "start") return "flex-start";
  if (align === "end") return "flex-end";
  return align as CSSProperties["alignItems"];
}

function mapJustify(
  justify?: FlexProps["justify"],
): CSSProperties["justifyContent"] {
  if (justify === "start") return "flex-start";
  if (justify === "end") return "flex-end";
  if (justify === "between") return "space-between";
  if (justify === "around") return "space-around";
  if (justify === "evenly") return "space-evenly";
  return justify as CSSProperties["justifyContent"];
}

export function Flex({
  children,
  className,
  direction = "row",
  gap,
  align,
  justify,
  wrap,
  height,
  mt,
  mb,
  style,
}: FlexProps) {
  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: direction,
        gap: toSpacingValue(gap),
        alignItems: mapAlign(align),
        justifyContent: mapJustify(justify),
        flexWrap: wrap === true ? "wrap" : wrap === false ? undefined : wrap,
        height,
        ...withSpacingStyle({ mt, mb, style }),
      }}
    >
      {children}
    </div>
  );
}

type CardProps = Omit<AntCardProps, "size" | "variant"> & {
  asChild?: boolean;
  size?: "1" | "2" | "3" | string;
  variant?: "surface" | string;
  children?: ReactNode;
};

const AntCardComponent = AntCard as unknown as (props: AntCardProps) => ReactElement;

export function Card({
  asChild = false,
  size,
  variant,
  className,
  children,
  ...rest
}: CardProps) {
  void variant;
  const mappedSize = size === "2" ? "small" : "default";

  if (asChild && isValidElement(children)) {
    const child = Children.only(children) as ReactElement<{
      className?: string;
      children?: ReactNode;
    }>;
    return cloneElement(
      child,
      { className: cn("block", child.props.className) },
      <AntCardComponent {...rest} className={className} size={mappedSize}>
        {child.props.children}
      </AntCardComponent>,
    );
  }

  return (
    <AntCardComponent {...rest} className={className} size={mappedSize}>
      {children}
    </AntCardComponent>
  );
}

type TextFieldRootProps = Omit<React.ComponentProps<typeof Input>, "size"> & {
  size?: "1" | "2" | "3" | string;
  mt?: string | number;
  mb?: string | number;
};

function TextFieldRoot({
  size,
  mt,
  mb,
  style,
  ...rest
}: TextFieldRootProps) {
  return (
    <Input
      {...rest}
      size={mapInputSize(size)}
      style={withSpacingStyle({ mt, mb, style })}
    />
  );
}

export const TextField = {
  Root: TextFieldRoot,
} as const;

type TextAreaProps = Omit<React.ComponentProps<typeof Input.TextArea>, "size"> & {
  size?: "1" | "2" | "3" | string;
  mt?: string | number;
  mb?: string | number;
};

export function TextArea({ size, mt, mb, style, ...rest }: TextAreaProps) {
  return (
    <Input.TextArea
      {...rest}
      size={mapInputSize(size)}
      style={withSpacingStyle({ mt, mb, style })}
    />
  );
}

type SelectOption = {
  value: string;
  label: ReactNode;
  disabled?: boolean;
};

type SelectRootProps = {
  value?: string;
  onValueChange?: (value: string) => void;
  disabled?: boolean;
  children?: ReactNode;
  className?: string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

type SelectTriggerProps = {
  className?: string;
  placeholder?: string;
  "aria-label"?: string;
};

type SelectContentProps = {
  children?: ReactNode;
};

type SelectItemProps = {
  value: string;
  children?: ReactNode;
  disabled?: boolean;
};

function SelectTrigger(_props: SelectTriggerProps) {
  void _props;
  return null;
}

function SelectContent(_props: SelectContentProps) {
  void _props;
  return null;
}

function SelectItem(_props: SelectItemProps) {
  void _props;
  return null;
}

function collectSelectItems(children: ReactNode, bucket: SelectOption[]) {
  Children.forEach(children, (node) => {
    if (!isValidElement(node)) {
      return;
    }
    if (node.type === SelectItem) {
      const props = node.props as SelectItemProps;
      bucket.push({
        value: props.value,
        label: props.children,
        disabled: props.disabled,
      });
      return;
    }
    if (node.type === Fragment || (node.props as { children?: ReactNode }).children) {
      collectSelectItems((node.props as { children?: ReactNode }).children, bucket);
    }
  });
}

function SelectRoot({
  value,
  onValueChange,
  disabled,
  children,
  className,
  mt,
  mb,
  style,
}: SelectRootProps) {
  let triggerProps: SelectTriggerProps = {};
  const options: SelectOption[] = [];

  Children.forEach(children, (node) => {
    if (!isValidElement(node)) {
      return;
    }
    if (node.type === SelectTrigger) {
      triggerProps = node.props as SelectTriggerProps;
      return;
    }
    if (node.type === SelectContent) {
      collectSelectItems((node.props as SelectContentProps).children, options);
      return;
    }
    if (node.type === SelectItem) {
      const props = node.props as SelectItemProps;
      options.push({
        value: props.value,
        label: props.children,
        disabled: props.disabled,
      });
    }
  });

  return (
    <AntSelect
      aria-label={triggerProps["aria-label"]}
      className={cn(triggerProps.className, className)}
      disabled={disabled}
      onChange={(nextValue: unknown) => onValueChange?.(String(nextValue))}
      options={options}
      placeholder={triggerProps.placeholder}
      style={{
        width: "100%",
        ...withSpacingStyle({ mt, mb, style }),
      }}
      value={value}
    />
  );
}

export const Select = {
  Root: SelectRoot,
  Trigger: SelectTrigger,
  Content: SelectContent,
  Item: SelectItem,
} as const;

type DialogContextValue = {
  open: boolean;
  setOpen: (nextOpen: boolean) => void;
};

const DialogContext = createContext<DialogContextValue | null>(null);

type DialogRootProps = {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (nextOpen: boolean) => void;
  children?: ReactNode;
};

function DialogRoot({
  open,
  defaultOpen = false,
  onOpenChange,
  children,
}: DialogRootProps) {
  const [innerOpen, setInnerOpen] = useState(defaultOpen);
  const mergedOpen = open ?? innerOpen;

  const setOpen = (nextOpen: boolean) => {
    if (open === undefined) {
      setInnerOpen(nextOpen);
    }
    onOpenChange?.(nextOpen);
  };

  return (
    <DialogContext.Provider value={{ open: mergedOpen, setOpen }}>
      {children}
    </DialogContext.Provider>
  );
}

type DialogContentProps = {
  children?: ReactNode;
  className?: string;
  maxWidth?: string;
};

function parseDialogWidth(maxWidth?: string): number | undefined {
  if (!maxWidth) {
    return undefined;
  }
  if (/^\d+px$/.test(maxWidth.trim())) {
    return Number(maxWidth.replace("px", ""));
  }
  return undefined;
}

function DialogContent({ children, className, maxWidth }: DialogContentProps) {
  const context = useContext(DialogContext);
  if (!context) {
    return null;
  }

  return (
    <AntModal
      className={className}
      destroyOnHidden
      footer={null}
      onCancel={() => context.setOpen(false)}
      open={context.open}
      width={parseDialogWidth(maxWidth)}
    >
      {children}
    </AntModal>
  );
}

type DialogTitleProps = {
  children?: ReactNode;
  className?: string;
};

function DialogTitle({ children, className }: DialogTitleProps) {
  return (
    <Typography.Title className={className} level={4} style={{ marginTop: 0 }}>
      {children}
    </Typography.Title>
  );
}

type DialogDescriptionProps = {
  children?: ReactNode;
  className?: string;
  size?: string;
};

function DialogDescription({
  children,
  className,
  size,
}: DialogDescriptionProps) {
  return (
    <Typography.Paragraph
      className={className}
      style={{ fontSize: mapTextSize(size), marginBottom: 16 }}
      type="secondary"
    >
      {children}
    </Typography.Paragraph>
  );
}

export const Dialog = {
  Root: DialogRoot,
  Content: DialogContent,
  Title: DialogTitle,
  Description: DialogDescription,
} as const;

type DropdownMenuTriggerProps = {
  children?: ReactNode;
};

type DropdownMenuContentProps = {
  children?: ReactNode;
  align?: "start" | "center" | "end";
  size?: string;
  variant?: string;
};

type DropdownMenuItemProps = {
  children?: ReactNode;
  color?: "gray" | "red" | "indigo" | string;
  disabled?: boolean;
  onSelect?: () => void;
  asChild?: boolean;
};

type DropdownMenuLabelProps = {
  children?: ReactNode;
};

function DropdownMenuTrigger(_props: DropdownMenuTriggerProps) {
  void _props;
  return null;
}

function DropdownMenuContent(_props: DropdownMenuContentProps) {
  void _props;
  return null;
}

function DropdownMenuItem(_props: DropdownMenuItemProps) {
  void _props;
  return null;
}

function DropdownMenuLabel(_props: DropdownMenuLabelProps) {
  void _props;
  return null;
}

function DropdownMenuSeparator() {
  return null;
}

type DropdownItems = NonNullable<MenuProps["items"]>;
type DropdownItem = NonNullable<DropdownItems[number]>;

function buildDropdownItems(children: ReactNode, prefix = "item"): DropdownItems {
  const items: DropdownItem[] = [];
  let index = 0;

  Children.forEach(children, (node) => {
    if (!isValidElement(node)) {
      return;
    }

    if (node.type === DropdownMenuSeparator) {
      items.push({ type: "divider" });
      return;
    }

    if (node.type === DropdownMenuLabel) {
      items.push({
        key: `${prefix}-label-${index++}`,
        disabled: true,
        label: (
          <span className="text-xs text-[var(--gray-11)]">
            {(node.props as DropdownMenuLabelProps).children}
          </span>
        ),
      });
      return;
    }

    if (node.type === DropdownMenuItem) {
      const props = node.props as DropdownMenuItemProps;
      items.push({
        key: `${prefix}-${index++}`,
        disabled: props.disabled,
        danger: props.color === "red",
        label: props.children,
        onClick: () => props.onSelect?.(),
      });
      return;
    }

    const nestedChildren = (node.props as { children?: ReactNode }).children;
    if (node.type === Fragment || nestedChildren) {
      const nestedItems = buildDropdownItems(nestedChildren, `${prefix}-${index++}`)
        .filter((item): item is DropdownItem => item !== null);
      items.push(...nestedItems);
    }
  });

  return items;
}

type DropdownMenuRootProps = {
  children?: ReactNode;
};

function DropdownMenuRoot({ children }: DropdownMenuRootProps) {
  let triggerNode: ReactNode = null;
  let contentProps: DropdownMenuContentProps | null = null;

  Children.forEach(children, (node) => {
    if (!isValidElement(node)) {
      return;
    }
    if (node.type === DropdownMenuTrigger) {
      triggerNode = (node.props as DropdownMenuTriggerProps).children;
      return;
    }
    if (node.type === DropdownMenuContent) {
      contentProps = node.props as DropdownMenuContentProps;
    }
  });

  const contentChildren = (contentProps as DropdownMenuContentProps | null)?.children;
  const contentAlign = (contentProps as DropdownMenuContentProps | null)?.align;
  const items = buildDropdownItems(contentChildren);
  const placement =
    contentAlign === "end"
      ? "bottomRight"
      : contentAlign === "center"
        ? "bottom"
        : "bottomLeft";

  return (
    <AntDropdown
      menu={{ items }}
      placement={placement}
      trigger={["click"]}
    >
      <span className="inline-flex cursor-pointer">{triggerNode}</span>
    </AntDropdown>
  );
}

export const DropdownMenu = {
  Root: DropdownMenuRoot,
  Trigger: DropdownMenuTrigger,
  Content: DropdownMenuContent,
  Item: DropdownMenuItem,
  Label: DropdownMenuLabel,
  Separator: DropdownMenuSeparator,
} as const;

type CalloutRootProps = {
  children?: ReactNode;
  color?: "red" | "green" | string;
  className?: string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

function CalloutRoot({
  children,
  color,
  className,
  mt,
  mb,
  style,
}: CalloutRootProps) {
  const type =
    color === "red" ? "error" : color === "green" ? "success" : "info";

  return (
    <Alert
      className={className}
      description={children}
      message=""
      showIcon
      style={withSpacingStyle({ mt, mb, style })}
      type={type}
    />
  );
}

type CalloutTextProps = {
  children?: ReactNode;
};

function CalloutText({ children }: CalloutTextProps) {
  return <>{children}</>;
}

export const Callout = {
  Root: CalloutRoot,
  Text: CalloutText,
} as const;

type CheckboxProps = Omit<React.ComponentProps<typeof AntCheckbox>, "onChange" | "checked"> & {
  checked?: boolean | "indeterminate";
  onCheckedChange?: (checked: boolean | "indeterminate") => void;
};

export function Checkbox({
  checked,
  onCheckedChange,
  children,
  ...rest
}: CheckboxProps) {
  return (
    <AntCheckbox
      {...rest}
      checked={checked === "indeterminate" ? false : checked}
      indeterminate={checked === "indeterminate"}
      onChange={(event: { target: { checked: boolean } }) =>
        onCheckedChange?.(event.target.checked)}
    >
      {children}
    </AntCheckbox>
  );
}

type TableRootProps = TableHTMLAttributes<HTMLTableElement>;
type TableSectionProps = HTMLAttributes<HTMLTableSectionElement>;
type TableRowProps = HTMLAttributes<HTMLTableRowElement>;
type TableHeaderCellProps = ThHTMLAttributes<HTMLTableCellElement>;
type TableCellProps = TdHTMLAttributes<HTMLTableCellElement>;

function TableRoot({ children, className, ...rest }: TableRootProps) {
  return (
    <table {...rest} className={cn("w-full border-collapse", className)}>
      {children}
    </table>
  );
}

function TableHeader({ children, className, ...rest }: TableSectionProps) {
  return (
    <thead {...rest} className={className}>
      {children}
    </thead>
  );
}

function TableBody({ children, className, ...rest }: TableSectionProps) {
  return (
    <tbody {...rest} className={className}>
      {children}
    </tbody>
  );
}

function TableRow({ children, className, ...rest }: TableRowProps) {
  return (
    <tr {...rest} className={className}>
      {children}
    </tr>
  );
}

function TableColumnHeaderCell({
  children,
  className,
  scope = "col",
  ...rest
}: TableHeaderCellProps) {
  return (
    <th {...rest} className={className} scope={scope}>
      {children}
    </th>
  );
}

function TableCell({ children, className, ...rest }: TableCellProps) {
  return (
    <td {...rest} className={className}>
      {children}
    </td>
  );
}

export const Table = {
  Root: TableRoot,
  Header: TableHeader,
  Body: TableBody,
  Row: TableRow,
  ColumnHeaderCell: TableColumnHeaderCell,
  Cell: TableCell,
} as const;
